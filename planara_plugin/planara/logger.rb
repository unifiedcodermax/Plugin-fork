# frozen_string_literal: true

module Planara
  # Lightweight logger for the plugin side.
  #
  # SketchUp's stdout goes to the Ruby Console window. We prefix
  # each line with [Planara] + ISO timestamp so messages stay
  # findable when other extensions are also chatty.
  #
  # No external gems (SketchUp's Ruby is sandboxed). No file I/O
  # by default — that would compete with SketchUp's own logging
  # and surprise users on read-only installs.
  module Logger
    LEVELS = { debug: 0, info: 1, warn: 2, error: 3 }.freeze

    module_function

    def level
      @level ||= LEVELS.fetch(
        (ENV['PLANARA_LOG_LEVEL'] || 'info').downcase.to_sym,
        LEVELS[:info]
      )
    end

    def debug(msg, **fields); write(:debug, msg, fields); end
    def info(msg,  **fields); write(:info,  msg, fields); end
    def warn(msg,  **fields); write(:warn,  msg, fields); end
    def error(msg, **fields); write(:error, msg, fields); end

    def write(severity, msg, fields)
      return if LEVELS[severity] < level

      ts = Time.now.utc.strftime('%Y-%m-%dT%H:%M:%S.%LZ')
      payload = fields.empty? ? '' : ' ' + fields.map { |k, v| "#{k}=#{v.inspect}" }.join(' ')
      puts "[Planara #{ts} #{severity.to_s.upcase}] #{msg}#{payload}"
    end
  end
end
