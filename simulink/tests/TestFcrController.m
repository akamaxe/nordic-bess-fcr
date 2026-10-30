classdef TestFcrController < matlab.unittest.TestCase
    %TESTFCRCONTROLLER Unit tests of the MATLAB controller and the Simulink twin.
    %   Mirrors tests/test_control.py and tests/test_simulation.py. Run with
    %   runtests('simulink/tests').

    properties
        P
    end

    methods (TestClassSetup)
        function addPaths(testCase)
            here = fileparts(mfilename('fullpath'));
            testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(here, '..')));
        end
    end

    methods (TestMethodSetup)
        function defaultParams(testCase)
            % Reference case of configs/base.yaml at 1 s steps.
            testCase.P = struct('dt_s', 1, 'steps_per_tick', 1, 'window_samples', 300, ...
                'p_max_mw', 10, 'e_nom_mwh', 20, 'e_min_mwh', 1, 'e_max_mwh', 19, ...
                'e0_mwh', 10, 'eta_c', 0.9487, 'eta_d', 0.9487, 'tau_s', 0.2, ...
                'nem_rate_n', 0.34, 'nem_rate_d', 0.20, 'energy_hours_d', 1/3, ...
                'min_n', [5 10 30 57.5], 'min_d', [5 10 20 20], ...
                'dc_voltage_v', 1200, 'internal_resistance_ohm', 5e-4);
        end
    end

    methods (Test)
        function table1ActivationPoints(testCase)
            cases = {  % caps, f, expected p_set
                [10 0 0], 50.0, 0; [10 0 0], 49.9, 10; [10 0 0], 50.1, -10;
                [10 0 0], 49.95, 5; [10 0 0], 49.7, 10;
                [0 10 0], 49.9, 0; [0 10 0], 49.7, 5; [0 10 0], 49.5, 10; [0 10 0], 49.0, 10;
                [0 0 10], 50.5, -10; [0 0 10], 51.0, -10; [0 0 10], 49.8, 0};
            for k = 1:size(cases, 1)
                state = fcr_controller_init(testCase.P);
                p = fcr_controller_step(cases{k, 2}, 10, cases{k, 1}, 0, state, testCase.P);
                testCase.verifyEqual(p, cases{k, 3}, 'AbsTol', 1e-9, ...
                    sprintf('caps %s, f = %g', mat2str(cases{k, 1}), cases{k, 2}));
            end
        end

        function nemChargesBelowThresholdInsideBand(testCase)
            c = 5;
            e = testCase.P.e_min_mwh + c * 0.5 - 0.01;   % below the FCR-N NEM enable level
            state = fcr_controller_init(testCase.P);
            for k = 1:400
                [p, state] = fcr_controller_step(50.0, e, [c 0 0], 0, state, testCase.P);
            end
            testCase.verifyEqual(state.nem_current(1), -1, 'AbsTol', 1e-12);
            testCase.verifyEqual(p, -0.34 * c, 'AbsTol', 1e-12);
            for k = 1:400   % outside the normal band NEM is disabled and ramps back
                [~, state] = fcr_controller_step(49.85, e, [c 0 0], 0, state, testCase.P);
            end
            testCase.verifyEqual(state.nem_current(1), 0, 'AbsTol', 1e-12);
            testCase.verifyEqual(state.nem_allowed(1), 0);
        end

        function nemStaysOffBetweenEnableAndDisable(testCase)
            c = 5;
            e = testCase.P.e_min_mwh + c * 0.7;   % between 30 min (enable) and 57.5 min
            state = fcr_controller_init(testCase.P);
            for k = 1:400
                [~, state] = fcr_controller_step(50.0, e, [c 0 0], 0, state, testCase.P);
            end
            testCase.verifyEqual(state.nem_current(1), 0);
        end

        function aemExhaustsFcrDUpSmoothly(testCase)
            c = 9;
            e = testCase.P.e_min_mwh + c * 5 / 60 - 0.02;   % below the AEM enable level
            state = fcr_controller_init(testCase.P);
            p = zeros(1, 400);
            for k = 1:400
                [p(k), state] = fcr_controller_step(49.5, e, [0 c 0], 0, state, testCase.P);
            end
            testCase.verifyTrue(state.aem_low(2));
            testCase.verifyEqual(p(1), c, 'AbsTol', 1e-12);
            testCase.verifyEqual(p(151), c / 2, 'RelTol', 0.02);
            testCase.verifyLessThan(abs(p(310)), 1e-9);
            testCase.verifyTrue(all(diff(p(1:305)) <= 1e-9));
        end

        function twinReachesFullActivationWithLag(testCase)
            tmp = testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
            P = testCase.P;
            P.dt_s = 0.1; P.steps_per_tick = 10;
            model = build_bess_fcr_twin(P, tmp.Folder);
            testCase.addTeardown(@() close_system(model, 0));
            t = (0:0.1:5)';
            f = 49.9 * ones(size(t)); f(t >= 1) = 49.5;
            in = Simulink.SimulationInput(model);
            in = in.setVariable('f_ts', timeseries(f, t)).setVariable('caps', [0 10 0]) ...
                .setVariable('p_base', 0).setVariable('stop_time', 5).setVariable('P', P);
            out = sim(in);
            tt = out.p_out.Time; p = out.p_out.Data;
            % First-order lag of 0.2 s after the frequency step at t = 1 s.
            on = tt >= 1 - 1e-9;
            expected = 10 * (1 - exp(-(tt(on) - 1) / 0.2));
            testCase.verifyEqual(p(on), expected, 'AbsTol', 1e-3);
            testCase.verifyLessThan(out.q_ah.Data(end), out.q_ah.Data(1));  % discharging
        end
    end
end
