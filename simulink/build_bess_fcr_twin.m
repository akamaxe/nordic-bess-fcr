function model = build_bess_fcr_twin(P, model_dir)
%BUILD_BESS_FCR_TWIN Build the Simulink digital twin of the BESS (PLAN M5).
%   MODEL = BUILD_BESS_FCR_TWIN(P, MODEL_DIR) creates and saves bess_fcr_twin.slx.
%   P is the parameter struct from simulink/inputs/params.json (scripts/
%   export_twin_inputs.py, values from configs/base.yaml).
%
%   Structure
%     controller  MATLAB Function block calling fcr_controller_step (mirrors droop.py and
%                 energy_mgmt.py), sampled every P.dt_s
%     converter   average power-level model: setpoint saturation, first-order lag tau,
%                 BMS clip at the energy limits, charge and discharge efficiencies
%     storage     stored energy integrated from the DC power (same accounting as Python)
%     DC network  Simscape Electrical Battery fed by a controlled current source
%                 I = P_dc / V_dc (V_dc measured, delayed by one sample to avoid an
%                 algebraic loop); it adds battery voltage and charge to the outputs
%   The AC side is not modelled: the frequency is an input (grid-following unit).

model = 'bess_fcr_twin';
if bdIsLoaded(model), close_system(model, 0); end
slx = fullfile(model_dir, [model '.slx']);
if isfile(slx), delete(slx); end   % rebuilt from scratch, so the model is reproducible
new_system(model);
load_system('simulink'); load_system('ee_lib'); load_system('fl_lib'); load_system('nesl_utility');
dt = num2str(P.dt_s);

% --- inputs ---------------------------------------------------------------------------
add('simulink/Sources/From Workspace', 'f_in', [30 40 110 70], ...
    'VariableName', 'f_ts', 'SampleTime', dt, 'Interpolate', 'off', ...
    'OutputAfterFinalValue', 'Holding final value');
add('simulink/Sources/Constant', 'caps', [30 100 110 130], 'Value', 'caps', 'SampleTime', dt);
add('simulink/Sources/Constant', 'p_base', [30 160 110 190], 'Value', 'p_base', 'SampleTime', dt);
add('simulink/Discrete/Zero-Order Hold', 'zoh_e', [140 220 180 250], 'SampleTime', dt);

% --- controller (MATLAB Function block) ------------------------------------------------
ctrl = [model '/controller'];
add_block('simulink/User-Defined Functions/MATLAB Function', ctrl, 'Position', [220 30 380 250]);
chart = find(sfroot, '-isa', 'Stateflow.EMChart', 'Path', ctrl);
chart.Script = strjoin({
    'function [p_set, p_fcr, p_nem] = controller(f, e_mwh, caps, p_base, P)'
    '%#codegen'
    '% Mirrors nordic_bess.sim.engine with nordic_bess.control (FCR v1.1, eq. 12-26).'
    'persistent state'
    'if isempty(state)'
    '    state = fcr_controller_init(P);'
    'end'
    '[p_set, state, p_fcr, p_nem] = fcr_controller_step(f, e_mwh, caps, p_base, state, P);'
    }, newline);
pdata = chart.find('-isa', 'Stateflow.Data', 'Name', 'P');
pdata.Scope = 'Parameter';

% --- converter and storage (Simulink) ----------------------------------------------------
add('simulink/Discontinuities/Saturation', 'sat_p', [420 40 460 70], ...
    'UpperLimit', num2str(P.p_max_mw), 'LowerLimit', num2str(-P.p_max_mw));
add('simulink/Continuous/Transfer Fcn', 'lag', [490 40 570 70], ...
    'Numerator', '1', 'Denominator', sprintf('[%g 1]', P.tau_s));
add('simulink/Discontinuities/Saturation Dynamic', 'bms', [610 30 650 80]);
add('simulink/Sources/Constant', 'e_min', [430 110 480 130], 'Value', num2str(P.e_min_mwh));
add('simulink/Sources/Constant', 'e_max', [430 150 480 170], 'Value', num2str(P.e_max_mwh));
add('simulink/Logic and Bit Operations/Relational Operator', 'can_dis', [520 100 550 130], 'Operator', '>');
add('simulink/Logic and Bit Operations/Relational Operator', 'can_ch', [520 145 550 175], 'Operator', '<');
add('simulink/Signal Attributes/Data Type Conversion', 'dbl_dis', [560 100 590 130], 'OutDataTypeStr', 'double');
add('simulink/Signal Attributes/Data Type Conversion', 'dbl_ch', [560 145 590 175], 'OutDataTypeStr', 'double');
add('simulink/Math Operations/Gain', 'up_lim', [600 100 630 130], 'Gain', num2str(P.p_max_mw));
add('simulink/Math Operations/Gain', 'lo_lim', [600 145 630 175], 'Gain', num2str(-P.p_max_mw));
add('simulink/Discontinuities/Saturation', 'pos', [690 20 720 50], 'UpperLimit', 'inf', 'LowerLimit', '0');
add('simulink/Discontinuities/Saturation', 'neg', [690 70 720 100], 'UpperLimit', '0', 'LowerLimit', '-inf');
add('simulink/Math Operations/Gain', 'inv_eta_d', [740 20 780 50], 'Gain', sprintf('1/%.10g', P.eta_d));
add('simulink/Math Operations/Gain', 'eta_c', [740 70 780 100], 'Gain', sprintf('%.10g', P.eta_c));
add('simulink/Math Operations/Sum', 'p_dc', [800 40 820 80], 'Inputs', '++');
add('simulink/Math Operations/Gain', 'to_mwh', [840 140 880 170], 'Gain', '-1/3600');
add('simulink/Continuous/Integrator', 'energy', [900 140 930 170], ...
    'InitialCondition', num2str(P.e0_mwh), 'LimitOutput', 'on', ...
    'UpperSaturationLimit', num2str(P.e_nom_mwh), 'LowerSaturationLimit', '0');

% --- DC network (Simscape Electrical) ------------------------------------------------------
add('simulink/Math Operations/Gain', 'to_w', [840 40 880 70], 'Gain', '1e6');
add('simulink/Discrete/Unit Delay', 'v_delay', [840 230 880 260], 'SampleTime', dt, ...
    'InitialCondition', num2str(P.dc_voltage_v));
add('simulink/Math Operations/Divide', 'i_ref', [900 40 930 80]);
add(sprintf('nesl_utility/Simulink-PS\nConverter'), 's2ps', [950 45 980 75], 'Unit', 'A');
add('fl_lib/Electrical/Electrical Sources/Controlled Current Source', 'isrc', [1010 40 1050 100]);
ah = P.e_nom_mwh * 1e6 / P.dc_voltage_v;
add('ee_lib/Sources/Battery', 'battery', [1120 40 1170 120], ...
    'Vnom', num2str(P.dc_voltage_v), 'R1', num2str(P.internal_resistance_ohm), ...
    'prm_AH', 'simscape.enum.battery.prm_AH.finite', 'AH', num2str(ah), ...
    'V1', num2str(0.98 * P.dc_voltage_v), 'AH1', num2str(ah / 2), ...
    'charge_measurement_port', 'simscape.enum.battery.enable.yes', ...
    'charge_specify', 'on', 'charge', num2str(ah * P.e0_mwh / P.e_nom_mwh), ...
    'charge_priority', 'High');
add('fl_lib/Electrical/Electrical Sensors/Voltage Sensor', 'vsense', [1120 170 1160 220]);
add('fl_lib/Electrical/Electrical Elements/Electrical Reference', 'gnd', [1200 250 1230 280]);
add(sprintf('nesl_utility/Solver\nConfiguration'), 'solver', [1010 250 1060 280]);
add(sprintf('nesl_utility/PS-Simulink\nConverter'), 'ps2s_v', [1190 180 1220 210]);
add(sprintf('nesl_utility/PS-Simulink\nConverter'), 'ps2s_q', [1240 60 1270 90], 'Unit', 'A*hr');

% --- logging ------------------------------------------------------------------------------
log_names = {'p_set', 'p_out', 'e_mwh', 'v_dc', 'q_ah', 'p_fcr', 'p_nem'};
for k = 1:numel(log_names)
    add('simulink/Sinks/To Workspace', ['log_' log_names{k}], [1300 40 + 50 * k 1360 70 + 50 * k], ...
        'VariableName', log_names{k}, 'SaveFormat', 'Timeseries', 'SampleTime', dt);
end

% --- signal lines -----------------------------------------------------------------------------
wire('f_in/1', 'controller/1'); wire('zoh_e/1', 'controller/2');
wire('caps/1', 'controller/3'); wire('p_base/1', 'controller/4');
wire('controller/1', 'sat_p/1'); wire('sat_p/1', 'lag/1');
wire('lag/1', 'bms/2'); wire('up_lim/1', 'bms/1'); wire('lo_lim/1', 'bms/3');
wire('energy/1', 'can_dis/1'); wire('e_min/1', 'can_dis/2');
wire('energy/1', 'can_ch/1'); wire('e_max/1', 'can_ch/2');
wire('can_dis/1', 'dbl_dis/1'); wire('dbl_dis/1', 'up_lim/1');
wire('can_ch/1', 'dbl_ch/1'); wire('dbl_ch/1', 'lo_lim/1');
wire('bms/1', 'pos/1'); wire('bms/1', 'neg/1');
wire('pos/1', 'inv_eta_d/1'); wire('neg/1', 'eta_c/1');
wire('inv_eta_d/1', 'p_dc/1'); wire('eta_c/1', 'p_dc/2');
wire('p_dc/1', 'to_mwh/1'); wire('to_mwh/1', 'energy/1'); wire('energy/1', 'zoh_e/1');
wire('p_dc/1', 'to_w/1'); wire('to_w/1', 'i_ref/1'); wire('v_delay/1', 'i_ref/2');
wire('i_ref/1', 's2ps/1'); wire('ps2s_v/1', 'v_delay/1');
wire('controller/1', 'log_p_set/1'); wire('bms/1', 'log_p_out/1');
wire('energy/1', 'log_e_mwh/1'); wire('ps2s_v/1', 'log_v_dc/1'); wire('ps2s_q/1', 'log_q_ah/1');
wire('controller/2', 'log_p_fcr/1'); wire('controller/3', 'log_p_nem/1');

% --- physical connections (port order checked by compiling the model) ----------------------
pc = @(blk) get_param([model '/' blk], 'PortHandles');
bat = pc('battery'); src = pc('isrc'); vs = pc('vsense');
% Port order found by probing domains: Battery L1 = +, L2 = q, R1 = -; Controlled Current
% Source L1 = +, R1 = iS, R2 = -; Voltage Sensor L1 = +, R1 = V, R2 = -.
link(pc('s2ps').RConn(1), src.RConn(1));       % current reference -> source input
link(src.LConn(1), bat.RConn(1));               % source + to battery -: I > 0 draws current
link(src.RConn(2), bat.LConn(1));               % out of battery +, i.e. discharges it
link(vs.LConn(1), bat.LConn(1));                % sensor + to battery +
link(vs.RConn(2), bat.RConn(1));                % sensor - to battery -
link(vs.RConn(1), pc('ps2s_v').LConn(1));       % voltage signal
link(bat.LConn(2), pc('ps2s_q').LConn(1));      % charge signal
link(pc('gnd').LConn(1), bat.RConn(1));
link(pc('solver').RConn(1), bat.RConn(1));

set_param(model, 'Solver', 'ode23t', 'MaxStep', dt, 'RelTol', '1e-7', ...
    'StopTime', 'stop_time', 'SaveOutput', 'off', 'SaveTime', 'off', 'ReturnWorkspaceOutputs', 'on');
save_system(model, fullfile(model_dir, [model '.slx']));

    function add(lib, name, pos, varargin)
        add_block(lib, [model '/' name], 'Position', pos, varargin{:});
    end
    function wire(a, b)
        add_line(model, a, b, 'autorouting', 'smart');
    end
    function link(h1, h2)
        add_line(model, h1, h2, 'autorouting', 'smart');
    end
end
