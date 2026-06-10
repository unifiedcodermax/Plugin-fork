# frozen_string_literal: true

require 'fileutils'
require 'tmpdir'
require 'uri'

require_relative '../logger'

module Planara
  module UI
    # Writes engine-rendered HTML to a tempfile and asks the OS to
    # open it in the user's default browser.
    #
    # Why a tempfile and not a fresh HtmlDialog: the HTML coming out
    # of /history/.../html is a complete standalone document, and
    # the user-facing affordances (zoom, find, print, copy URL into
    # an email) are all things a real browser does better than an
    # embedded webview. The trade-off — the file is on disk — is
    # acceptable because the user is already saving these reports
    # explicitly through "Save current run".
    module BrowserView
      module_function

      # Open a string of HTML in the default browser.
      #
      # @param html [String] the document body (must be valid HTML).
      # @param tag  [String] a short slug folded into the filename so
      #   the user can tell, eg, a diff from a single archive at a
      #   glance when they have a stack of tabs open.
      # @return [String] the absolute path of the file written.
      def open_html(html, tag: 'report')
        path = write_tempfile(html, tag: tag)
        ::UI.openURL(file_url(path))
        Logger.info('browser_opened', path: path)
        path
      end

      # -- internals ---------------------------------------------------------

      def write_tempfile(html, tag:)
        dir = File.join(Dir.tmpdir, 'planara')
        FileUtils.mkdir_p(dir)
        # Timestamp + random suffix avoids the "browser already has
        # this URL cached" surprise that would happen if we reused
        # a stable filename.
        stamp = Time.now.strftime('%Y%m%d-%H%M%S')
        path = File.join(dir, "planara-#{tag}-#{stamp}-#{rand(10_000)}.html")
        File.write(path, html)
        path
      end

      def file_url(path)
        # Build a file:// URL with the absolute path. Spaces and
        # non-ASCII chars in the tmpdir (eg macOS usernames) need to
        # be percent-encoded segment by segment.
        normalized = path.tr('\\', '/')
        normalized = "/#{normalized}" unless normalized.start_with?('/')
        encoded = normalized.split('/').map { |seg| URI.encode_www_form_component(seg).gsub('+', '%20') }.join('/')
        "file://#{encoded}"
      end
    end
  end
end
