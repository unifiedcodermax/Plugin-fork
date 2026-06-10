# frozen_string_literal: true

require 'fileutils'

require_relative 'config'
require_relative 'engine_client'
require_relative 'logger'

module Planara
  # Supervises the planara_engine sidecar process.
  #
  # Lifecycle:
  #   1. start
  #        - If the engine is already responding on the configured
  #          URL (someone ran it manually), reuse it: don't spawn
  #          a duplicate.
  #        - Otherwise spawn `planara-engine` (or the command in
  #          PLANARA_ENGINE_CMD) detached, with stdio redirected to
  #          a log file under planara_engine/.run/.
  #        - Poll /health until it returns 200 or the timeout
  #          elapses, then return.
  #   2. stop
  #        - If we spawned the engine, SIGTERM it; SIGKILL after a
  #          short grace period.
  #        - If we attached to a pre-existing process, leave it
  #          alone — we don't own it.
  module EngineSupervisor
    POLL_INTERVAL_S = 0.25
    STOP_GRACE_S    = 5.0

    module_function

    def status
      {
        spawned: spawned?,
        pid: @pid,
        url: Config.engine_url,
      }
    end

    def spawned?
      !@pid.nil?
    end

    def start
      if engine_reachable?
        Logger.info('engine_already_running', url: Config.engine_url)
        return :already_running
      end

      spawn_engine
      wait_for_ready
      :started
    rescue EngineClient::EngineError, RuntimeError => e
      Logger.error('engine_start_failed', error: e.message)
      stop
      raise
    end

    def stop
      return :not_spawned unless spawned?

      Logger.info('engine_stopping', pid: @pid)
      kill_pid(@pid)
      @pid = nil
      :stopped
    end

    # -- internals -----------------------------------------------------------

    def engine_reachable?
      EngineClient.health
      true
    rescue EngineClient::EngineError
      false
    end

    def spawn_engine
      cmd = resolve_engine_cmd
      run_dir = File.expand_path('../../.run', Config.plugin_root)
      FileUtils.mkdir_p(run_dir)
      log_path = File.join(run_dir, 'engine.log')

      Logger.info('engine_spawning', cmd: cmd, log: log_path)

      env = {
        'DYLD_LIBRARY_PATH' => nil,
        'DYLD_FRAMEWORK_PATH' => nil,
        'PYTHONPATH' => nil,
        'PYTHONHOME' => nil,
        'RUBYLIB' => nil,
        'GEM_HOME' => nil,
        'GEM_PATH' => nil
      }

      @pid = Process.spawn(
        env,
        [cmd, cmd],
        out: [log_path, 'w'],
        err: [:child, :out],
        pgroup: true # so we can clean up child processes the engine itself spawned
      )
      Process.detach(@pid)
    end

    # Resolve the engine command in priority order:
    #   1. PLANARA_ENGINE_CMD env var  (explicit override)
    #   2. Bundled PyInstaller binary  (shipped inside the .rbz)
    #   3. 'planara-engine' on PATH    (dev / pipx install)
    def resolve_engine_cmd
      if (env_cmd = Config.engine_cmd)
        Logger.info('engine_resolve', source: 'env', cmd: env_cmd)
        return env_cmd
      end

      if (bundled = Config.bundled_engine_path)
        Logger.info('engine_resolve', source: 'bundled', cmd: bundled)
        return bundled
      end

      Logger.info('engine_resolve', source: 'PATH', cmd: 'planara-engine')
      'planara-engine'
    end

    def wait_for_ready
      deadline = Time.now + Config.health_timeout_s
      attempts = 0

      loop do
        attempts += 1
        return if engine_reachable?

        if Time.now >= deadline
          raise "engine did not become ready within #{Config.health_timeout_s}s (#{attempts} attempts)"
        end

        sleep POLL_INTERVAL_S
      end
    end

    def kill_pid(pid)
      Process.kill('TERM', pid)
      deadline = Time.now + STOP_GRACE_S
      while Time.now < deadline
        return if process_dead?(pid)
        sleep 0.1
      end
      Logger.warn('engine_kill_force', pid: pid)
      Process.kill('KILL', pid)
    rescue Errno::ESRCH, Errno::ECHILD
      # Already gone; fine.
    end

    def process_dead?(pid)
      Process.getpgid(pid)
      false
    rescue Errno::ESRCH
      true
    end
  end
end
