%RUN_TWIN Build the BESS digital twin and run the exported FCR test signals (PLAN M5).
%   Prerequisite: uv run python scripts/export_twin_inputs.py --config configs/base.yaml
%   Output: simulink/outputs/<signal>.csv with t_s, p_set_mw, p_out_mw, e_mwh, v_dc_v,
%   q_ah, p_fcr_*_mw and p_nem_*_mw at the test-signal sample time. Then run
%   uv run python scripts/evaluate_twin.py --config configs/base.yaml

here = fileparts(mfilename('fullpath'));
addpath(here);
in_dir = fullfile(here, 'inputs');
out_dir = fullfile(here, 'outputs');
if ~isfolder(out_dir), mkdir(out_dir); end

P = jsondecode(fileread(fullfile(in_dir, 'params.json')));
P.min_n = P.min_n(:)';
P.min_d = P.min_d(:)';
manifest = jsondecode(fileread(fullfile(in_dir, 'manifest.json')));
model = build_bess_fcr_twin(P, here);

for k = 1:numel(manifest)
    m = manifest(k);
    data = readmatrix(fullfile(in_dir, [m.name '.csv']), 'NumHeaderLines', 1);
    f_ts = timeseries(data(:, 2), data(:, 1));
    caps = m.caps_mw(:)';
    p_base = 0;
    stop_time = data(end, 1);
    in = Simulink.SimulationInput(model);
    in = in.setVariable('f_ts', f_ts).setVariable('caps', caps).setVariable('p_base', p_base) ...
        .setVariable('stop_time', stop_time).setVariable('P', P);
    tic; out = sim(in); elapsed = toc;
    t = out.p_out.Time;
    keep = t <= stop_time + 1e-9;
    cols = [t, out.p_set.Data, out.p_out.Data, out.e_mwh.Data, out.v_dc.Data, ...
            out.q_ah.Data, as_columns(out.p_fcr.Data, numel(t)), as_columns(out.p_nem.Data, numel(t))];
    T = array2table(cols(keep, :), 'VariableNames', {'t_s', 'p_set_mw', 'p_out_mw', ...
        'e_mwh', 'v_dc_v', 'q_ah', 'p_fcr_n_mw', 'p_fcr_dup_mw', 'p_fcr_ddown_mw', ...
        'p_nem_n_mw', 'p_nem_dup_mw', 'p_nem_ddown_mw'});
    writetable(T, fullfile(out_dir, [m.name '.csv']));
    fprintf('%s: %d samples in %.1f s\n', m.name, height(T), elapsed);
end

function x = as_columns(data, n)
% [1x3] signals are logged as 1x3xN or Nx3; return N x 3.
x = squeeze(data);
if size(x, 1) ~= n
    x = x.';
end
end
