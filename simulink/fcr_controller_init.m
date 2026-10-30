function state = fcr_controller_init(P)
%FCR_CONTROLLER_INIT Initial state of the FCR controller (mirrors nordic_bess.sim.engine).
%   STATE = FCR_CONTROLLER_INIT(P) returns the controller state for the parameter
%   struct P written by scripts/export_twin_inputs.py. Product order: FCR-N, FCR-D up,
%   FCR-D down. NEM windows start at 0 and AEM windows at f0 (no history), as in Python.

f0 = [50.0 49.9 50.1];
N = P.window_samples;
state.k = 0;                                  % step counter
state.pos = 1;                                % position in the 300-sample windows
state.nem_buf = zeros(3, N);                  % NEM_allowed history (eq. 15)
state.faem_buf = repmat(f0(:), 1, N);         % f_AEM history (eq. 18)
state.nem_low = false(1, 3);
state.nem_high = false(1, 3);
state.aem_low = false(1, 3);
state.aem_high = false(1, 3);
state.nem_current = zeros(1, 3);
state.nem_allowed = zeros(1, 3);
state.f_ref = f0;
end
