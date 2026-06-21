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
  #        - If a PID file exists from a crashed previous session,
  #          kill the orphaned process and re-spawn fresh.
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
  #        - Remove the PID file so the next session doesn't
  #          mistakenly kill a legitimately running engine.
  module EngineSupervisor
    POLL_INTERVAL_S = 0.25
    STOP_GRACE_S    = 5.0

    module_function

    def run_dir
      File.expand_path('../../.run', Config.plugin_root)
    end

    def pid_file_path
      File.join(run_dir, 'engine.pid')
    end

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
        # Check if this is a stale process from a crashed session
        if stale_pid_file?
          stale_pid = read_pid_file
          Logger.warn('engine_stale_process', pid: stale_pid)
          kill_pid(stale_pid) rescue nil
          delete_pid_file
          sleep 0.5
        else
          Logger.info('engine_already_running', url: Config.engine_url)
          return :already_running
        end
      end

      spawn_engine
      write_pid_file(@pid)
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
      delete_pid_file
      :stopped
    end

    # -- internals -----------------------------------------------------------

    def engine_reachable?
      EngineClient.health
      true
    rescue EngineClient::EngineError
      false
    end

    # -- PID file management -------------------------------------------------

    def write_pid_file(pid)
      FileUtils.mkdir_p(run_dir)
      File.write(pid_file_path, pid.to_s)
    rescue StandardError => e
      Logger.warn('pid_file_write_failed', error: e.message)
    end

    def read_pid_file
      return nil unless File.exist?(pid_file_path)
      File.read(pid_file_path).strip.to_i
    rescue StandardError
      nil
    end

    def delete_pid_file
      File.delete(pid_file_path) if File.exist?(pid_file_path)
    rescue StandardError => e
      Logger.warn('pid_file_delete_failed', error: e.message)
    end

    # A PID file is "stale" when it exists but the PID it records is
    # not the one we spawned in THIS session (i.e., @pid is nil or
    # different). This means a previous SketchUp session crashed
    # without calling stop, leaving an orphaned engine process.
    def stale_pid_file?
      stored = read_pid_file
      return false unless stored && stored > 0
      # If we spawned it ourselves this session, it's not stale
      return false if @pid && @pid == stored
      # Verify the process is actually running
      begin
        Process.kill(0, stored)
        true  # Process exists and we didn't spawn it — stale
      rescue Errno::ESRCH
        # Process is dead; clean up the PID file
        delete_pid_file
        false
      rescue Errno::EPERM
        true  # Process exists but owned by another user — treat as stale
      end
    end

    def spawn_engine
      cmd = resolve_engine_cmd
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
        'GEM_PATH' => nil,
        'PLANARA_ENV' => 'prod'
      }

      opts = {
        out: [log_path, 'w'],
        err: [:child, :out]
      }
      if Gem.win_platform?
        opts[:new_pgroup] = true
      else
        opts[:pgroup] = true
      end

      @pid = Process.spawn(
        env,
        [cmd, cmd],
        opts
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
      sig = Gem.win_platform? ? 'KILL' : 'TERM'
      Process.kill(sig, pid)
      deadline = Time.now + STOP_GRACE_S
      while Time.now < deadline
        return if process_dead?(pid)
        sleep 0.1
      end
      unless Gem.win_platform?
        Logger.warn('engine_kill_force', pid: pid)
        Process.kill('KILL', pid)
      end
    rescue Errno::ESRCH, Errno::ECHILD
      # Already gone; fine.
    end

    def process_dead?(pid)
      if Gem.win_platform?
        begin
          Process.kill(0, pid)
          false
        rescue Errno::ESRCH
          true
        rescue
          # In case of EPERM or EINVAL, assume the process exists but is not dead
          false
        end
      else
        Process.getpgid(pid)
        false
      end
    rescue Errno::ESRCH
      true
    end
  end
end
