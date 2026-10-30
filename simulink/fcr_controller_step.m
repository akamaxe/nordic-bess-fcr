function [p_set, state, p_fcr, p_nem] = fcr_controller_step(f, e_mwh, caps, p_base, state, P)
%FCR_CONTROLLER_STEP One step of the per-product FCR controller with NEM and AEM.
%   [P_SET, STATE, P_FCR, P_NEM] = FCR_CONTROLLER_STEP(F, E_MWH, CAPS, P_BASE, STATE, P)
%   mirrors nordic_bess.sim.engine.FcrUnitSimulator and nordic_bess.control:
%     - droop per product, eq. 23 with the saturations of eq. 20-22 (FCR v1.1);
%     - every second: AEM and NEM latches with Table 11 hysteresis (eq. 14) and the
%       300-sample rolling means of NEM_allowed (eq. 15) and f_AEM (eq. 18-19);
%     - NEM power (eq. 16-17) and the output limits of eq. 24-26.
%   Inputs: F frequency [Hz], E_MWH stored energy [MWh], CAPS = [C_N C_Dup C_Ddown] [MW],
%   P_BASE baseline [MW]. Outputs: total setpoint, per-product activation and NEM power
%   [MW]. Positive power = discharge (upward regulation). Codegen compatible.

f0 = [50.0 49.9 50.1];
df_max = [0.1 0.4 0.4];
rate = [P.nem_rate_n P.nem_rate_d P.nem_rate_d];
th = stacked_thresholds(caps, P);   % 3 x 8, columns as in energy_mgmt.EnergyThresholds
N = P.window_samples;

if mod(state.k, P.steps_per_tick) == 0
    pos = state.pos;
    for x = 1:3
        state.nem_current(x) = mean(state.nem_buf(x, :));   % previous 300 samples
        state.f_ref(x) = mean(state.faem_buf(x, :));
        if caps(x) <= 0
            state.nem_low(x) = false; state.nem_high(x) = false;
            state.aem_low(x) = false; state.aem_high(x) = false;
            state.nem_allowed(x) = 0;
            state.nem_buf(x, pos) = 0;
            state.faem_buf(x, pos) = f0(x);
            continue
        end
        % AEM latches (independent of frequency)
        if state.aem_low(x), lo_t = th(x, 2); else, lo_t = th(x, 1); end
        if state.aem_high(x), hi_t = th(x, 7); else, hi_t = th(x, 8); end
        state.aem_low(x) = e_mwh < lo_t;
        state.aem_high(x) = e_mwh > hi_t;
        % NEM latches, only inside the normal band (eq. 14)
        allowed = 0;
        if f > 49.9 && f < 50.1
            if state.nem_low(x), lo_t = th(x, 4); else, lo_t = th(x, 3); end
            if state.nem_high(x), hi_t = th(x, 5); else, hi_t = th(x, 6); end
            low = e_mwh < lo_t;
            high = e_mwh > hi_t;
            if low
                allowed = -1; state.nem_low(x) = true; state.nem_high(x) = false;
            elseif high
                allowed = 1; state.nem_low(x) = false; state.nem_high(x) = true;
            else
                state.nem_low(x) = false; state.nem_high(x) = false;
            end
        else
            state.nem_low(x) = false; state.nem_high(x) = false;
        end
        state.nem_allowed(x) = allowed;
        state.nem_buf(x, pos) = allowed;
        aem_on = state.aem_low(x) || state.aem_high(x);
        state.faem_buf(x, pos) = f_aem(x, f, aem_on, f0);
    end
    state.pos = mod(pos, N) + 1;
end

p_set = p_base;
p_fcr = zeros(1, 3);
p_nem = zeros(1, 3);
for x = 1:3
    c = caps(x);
    if c <= 0
        continue
    end
    if x == 1
        fs = min(max(f, 49.9), 50.1);
        px = c / df_max(x) * (state.f_ref(x) - fs);
    elseif x == 2
        px = min(c / df_max(x) * (state.f_ref(x) - min(f, 49.9)), c);
    else
        px = max(c / df_max(x) * (state.f_ref(x) - max(f, 50.1)), -c);
    end
    pn = rate(x) * c * state.nem_current(x);
    pt = px + pn;
    pmax = rate(x) * c;
    if x == 1
        pt = min(max(pt, -(c + pmax)), c + pmax);    % eq. 24
    elseif x == 2
        pt = max(pt, -pmax);                          % eq. 25
    else
        pt = min(pt, pmax);                           % eq. 26
    end
    p_fcr(x) = pt - pn;
    p_nem(x) = pn;
    p_set = p_set + pt;
end
state.k = state.k + 1;
end

function v = f_aem(x, f, aem_on, f0)
% Frequency fed to the AEM reference average (eq. 19-22).
if ~aem_on
    v = f0(x);
elseif x == 1
    v = min(max(f, 49.9), 50.1);
elseif x == 2
    v = min(f, 49.9);
else
    v = max(f, 50.1);
end
end

function th = stacked_thresholds(caps, P)
% Table 11 thresholds as stored energy [MWh] (mirrors energy_mgmt.stacked_thresholds).
% Columns: aem_en_lo aem_dis_lo nem_en_lo nem_dis_lo nem_dis_hi nem_en_hi aem_dis_hi aem_en_hi
reserve_up = P.energy_hours_d * caps(2);
reserve_dn = P.energy_hours_d * caps(3);
lo = [P.e_min_mwh + reserve_up, P.e_min_mwh, P.e_min_mwh];
hi = [P.e_max_mwh - reserve_dn, P.e_max_mwh, P.e_max_mwh];
mins = [P.min_n; P.min_d; P.min_d];   % rows: [aem_enable aem_disable nem_enable nem_disable]
th = nan(3, 8);
for x = 1:3
    c = caps(x);
    m = mins(x, :);
    if x ~= 3
        th(x, 1:4) = lo(x) + c * m([1 2 3 4]) / 60;
    end
    if x ~= 2
        th(x, 5:8) = hi(x) - c * m([4 3 2 1]) / 60;
    end
end
end
