# frozen_string_literal: true

require 'net/http'
require 'uri'
require 'json'

require_relative 'logger'

module Planara
  # Background version checker that pings the GitHub Releases API
  # to see if a newer .rbz is available.
  #
  # The check runs once per SketchUp session (not per model open).
  # It is non-blocking: we fire a thread and only display a dialog
  # when the thread completes with an update. No data is collected;
  # the only network call is a GET to api.github.com.
  #
  # To disable: set the environment variable PLANARA_SKIP_UPDATE_CHECK=1
  module UpdateChecker
    GITHUB_OWNER = 'JAGADISHSUNILPEDNEKAR'
    GITHUB_REPO  = 'Planara-Plugin'
    RELEASES_URL = "https://api.github.com/repos/#{GITHUB_OWNER}/#{GITHUB_REPO}/releases/latest"

    # How long to wait for the GitHub API before giving up (seconds).
    TIMEOUT_S = 10

    module_function

    # Kick off a background check. Safe to call multiple times —
    # only the first call in a session actually fires the request.
    def check_once
      return if @checked
      return if ENV['PLANARA_SKIP_UPDATE_CHECK'] == '1'

      @checked = true
      Thread.new { do_check }
    end

    # Visible for testing — synchronous version of the check.
    # Returns { update_available: bool, latest: "x.y.z", current: "x.y.z", url: "..." }
    def do_check
      current = current_version
      latest_info = fetch_latest_release
      return unless latest_info

      latest_tag = latest_info['tag_name'].to_s.sub(/\Av/, '')
      download_url = release_download_url(latest_info)

      if newer?(latest_tag, current)
        Logger.info(
          'update_available',
          current: current,
          latest: latest_tag,
          url: download_url
        )
        notify_user(current, latest_tag, download_url)
      else
        Logger.info('update_check_ok', current: current, latest: latest_tag)
      end

      { update_available: newer?(latest_tag, current),
        latest: latest_tag,
        current: current,
        url: download_url }
    rescue StandardError => e
      # Never crash the plugin for a failed update check.
      Logger.debug('update_check_failed', error: e.message)
      nil
    end

    # -- internals ---------------------------------------------------------

    def current_version
      Planara::EXTENSION_VERSION
    end

    # Compare two dotted version strings. Returns true when remote > local.
    def newer?(remote, local)
      remote_parts = remote.split('.').map(&:to_i)
      local_parts  = local.split('.').map(&:to_i)

      # Pad to equal length with zeros
      max_len = [remote_parts.length, local_parts.length].max
      remote_parts.fill(0, remote_parts.length...max_len)
      local_parts.fill(0, local_parts.length...max_len)

      (remote_parts <=> local_parts) == 1
    end

    def fetch_latest_release
      uri = URI.parse(RELEASES_URL)
      http = Net::HTTP.new(uri.host, uri.port)
      http.use_ssl = true
      http.open_timeout = TIMEOUT_S
      http.read_timeout = TIMEOUT_S

      req = Net::HTTP::Get.new(uri.request_uri)
      req['Accept'] = 'application/vnd.github+json'
      req['User-Agent'] = "Planara-Plugin/#{current_version}"

      response = http.request(req)
      return nil unless response.code.to_i == 200

      JSON.parse(response.body)
    rescue StandardError => e
      Logger.debug('github_api_error', error: e.message)
      nil
    end

    # Find the .rbz asset URL for the current platform.
    def release_download_url(release_info)
      platform = Gem.win_platform? ? 'windows' : 'macos'
      assets = release_info['assets'] || []

      asset = assets.find { |a| a['name'].to_s.include?(platform) && a['name'].to_s.end_with?('.rbz') }
      asset ? asset['browser_download_url'] : release_info['html_url']
    end

    def notify_user(current, latest, url)
      # UI.messagebox must be called on SketchUp's main thread.
      # Thread.new fires this in a background thread, so we use
      # UI.start_timer with 0 delay to marshal back.
      ::UI.start_timer(0, false) do
        result = ::UI.messagebox(
          "A new version of Planara is available!\n\n" \
          "Current: v#{current}\n" \
          "Latest:  v#{latest}\n\n" \
          "Would you like to open the download page?",
          MB_YESNO
        )

        if result == IDYES
          ::UI.openURL(url)
        end
      end
    end
  end
end
