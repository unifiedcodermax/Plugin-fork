# Planara Plugin Distribution & Shippability Guide

This guide details the strategies, concrete technical steps, and architecture adjustments required to package **Planara** (a hybrid SketchUp Ruby extension + Python FastAPI engine) into a polished, production-ready product that other architects can install and use with zero manual command-line setup.

---

## 1. Architectural Strategy Comparison

To distribute a hybrid application to end-users who are not software developers, we must choose how we package the engine:

| Strategy | Architecture | Install Friction | File Size | Maintenance & Updates | Offline Capable |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Option A: Cloud API (SaaS)** *(Highly Recommended)* | The Ruby plugin runs locally inside SketchUp and makes HTTP requests to a secure, cloud-hosted FastAPI engine (e.g. on AWS/Render). | **Extremely Low**<br>Standard `.rbz` install. Zero Python or local executables required. | **Tiny (< 1 MB)**<br>Only includes Ruby code and HTML/JS/CSS assets. | **Instant & Centralized**<br>Update a rule-pack on the server, and all users get the changes instantly. | **No**<br>Requires an internet connection. |
| **Option B: Local Sidecar (Offline-First)** | Compile the Python FastAPI engine into platform-specific executables (Windows `.exe`, macOS bin) using PyInstaller and bundle them in the `.rbz`. | **Medium**<br>Standard `.rbz` install, but may trigger OS Gatekeeper / antivirus prompts. | **Large (~80–120 MB)**<br>Bundles the Python interpreter, FastAPI, NumPy, Shapely, and GEOS. | **High Friction**<br>Requires users to re-download and install a new `.rbz` whenever bylaws change. | **Yes**<br>Runs completely locally on the architect's machine. |

---

## 2. Option A: Implementing the Cloud API Strategy (Recommended)

This strategy turns the Python backend into a centralized service. This matches standard SaaS patterns and is highly suited for team collaboration and instantaneous compliance updates.

```mermaid
sequenceDiagram
    participant SU as SketchUp (Ruby Client)
    participant Cloud as Cloud API (FastAPI)
    participant DB as Production DB (PostgreSQL)

    SU->>Cloud: POST /auth/login (JWT)
    Cloud-->>SU: Return JWT Token
    SU->>Cloud: POST /validate (Snapshot + JWT)
    Note over Cloud: Runs Shapely compliance logic
    Cloud-->>SU: Return Violations & Metrics
    SU->>Cloud: POST /history (Persist Run)
    Cloud->>DB: Write to database
    Cloud-->>SU: Return report_id
```

### Step 1: Deploying the FastAPI Engine
1. **Database Migration**: Swap the SQLite database in production for a managed relational database like **PostgreSQL** or **Supabase**. In [database.py](file:///Users/jagadishsunilpednekar/Planara-Plugin/planara_engine/src/planara_engine/persistence/database.py#L43-L60), swapping is as simple as setting the `PLANARA_DB_URL` environment variable:
   ```bash
   PLANARA_DB_URL=postgresql://user:password@host:5432/dbname
   ```
2. **Hosting Providers**: Deploy the containerized FastAPI app to modern PaaS platforms like **Render**, **Fly.io**, or **AWS App Runner**. A simple `Dockerfile` at the root of `planara_engine` builds the service:
   ```dockerfile
   FROM python:3.11-slim
   RUN apt-get update && apt-get install -y libgeos-dev && rm -rf /var/lib/apt/lists/*
   WORKDIR /app
   COPY . .
   RUN pip install --no-cache-dir .
   EXPOSE 8765
   CMD ["uvicorn", "planara_engine.api.app:app", "--host", "0.0.0.0", "--port", "8765"]
   ```

### Step 2: Modifying the Ruby Client
Point the client to the cloud API by default.
In [config.rb](file:///Users/jagadishsunilpednekar/Planara-Plugin/planara_plugin/planara/config.rb#L20-L26), change the default URL to your production server:

```ruby
    # @return [String] base URL for the engine, e.g. "https://api.planara.app"
    def engine_url
      ENV.fetch('PLANARA_ENGINE_URL', 'https://api.planara.app')
    end
```

In [boot.rb](file:///Users/jagadishsunilpednekar/Planara-Plugin/planara_plugin/planara/boot.rb#L39-L47), remove or bypass the `EngineSupervisor` calls:

```ruby
    def activate
      Logger.info('plugin_activating', summary: Config.summary)

      # In Cloud Mode, we do not need to spawn a local engine sidecar process!
      # We skip EngineSupervisor.start entirely.

      if Session.authenticated?
        on_authenticated
      else
        UI::LoginDialog.show(on_success: method(:on_authenticated))
      end
    end
```

---

## 3. Option B: Implementing the Local Sidecar Strategy (Offline-First)

If your user base requires working offline, you must build compiled, platform-specific binaries for the FastAPI service.

### Step 1: Compiling with PyInstaller
Run PyInstaller inside the `planara_engine` workspace to package the FastAPI app into a single standalone executable.

> [!WARNING]
> You must build the macOS binary on a Mac, and the Windows binary on a Windows machine. PyInstaller does not support cross-compilation.

1. Install PyInstaller in your Python environment:
   ```bash
   pip install pyinstaller
   ```
2. Create a entry-point script `entry.py` at the root of `planara_engine`:
   ```python
   import uvicorn
   from planara_engine.api.app import app
   from planara_engine.cli import main

   if __name__ == "__main__":
       # You can run CLI commands or run the web server directly
       import sys
       if len(sys.argv) > 1 and sys.argv[1] == "run-server":
           uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")
       else:
           main()
   ```
3. Run PyInstaller, ensuring we bundle the JSON rule packs:
   ```bash
   pyinstaller --onefile \
               --name planara-engine \
               --add-data "src/planara_engine/rules/packs/*.json:planara_engine/rules/packs" \
               entry.py
   ```
   *(On Windows, replace the `:` separator in `--add-data` with `;`)*.

### Step 2: Critical Code Adjustment (SQLite Path Fix)
As discovered in [database.py](file:///Users/jagadishsunilpednekar/Planara-Plugin/planara_engine/src/planara_engine/persistence/database.py#L49-L50), `project_root` uses `__file__`. In a frozen PyInstaller binary, `__file__` resolves to the temporary folder `/tmp/_MEIxxxx/` which is **wiped out on exit**, destroying the database.

To fix this, update [settings.py](file:///Users/jagadishsunilpednekar/Planara-Plugin/planara_engine/src/planara_engine/core/settings.py#L63) or [database.py](file:///Users/jagadishsunilpednekar/Planara-Plugin/planara_engine/src/planara_engine/persistence/database.py#L45-L53) to resolve `sqlite:///./planara.db` to the user's home directory when running compiled:

```python
        # In persistence/database.py
        if not db_path.is_absolute():
            # If frozen in a PyInstaller bundle, save database in the user's home directory
            if getattr(sys, 'frozen', False):
                home_dir = Path.home() / ".planara"
                home_dir.mkdir(parents=True, exist_ok=True)
                db_path = home_dir / db_path.name
            else:
                db_path = settings.project_root / db_path
```

### Step 3: Updating the Ruby supervisor to find the binary
Place the compiled executables in a `bin/` directory within the plugin directory:
* `planara_plugin/planara/bin/darwin/planara-engine` (macOS)
* `planara_plugin/planara/bin/windows/planara-engine.exe` (Windows)

Update [engine_supervisor.rb](file:///Users/jagadishsunilpednekar/Planara-Plugin/planara_plugin/planara/engine_supervisor.rb#L78-L93) to dynamically locate and spawn the bundled binary:

```ruby
    def spawn_engine
      # Check platform
      is_windows = (RbConfig::CONFIG['host_os'] =~ /mswin|mingw|cygwin/)
      platform_dir = is_windows ? 'windows' : 'darwin'
      binary_name = is_windows ? 'planara-engine.exe' : 'planara-engine'

      # Locate bundled binary in the extension folder
      bundled_cmd = File.join(Config.plugin_root, 'bin', platform_dir, binary_name)
      
      # Prefer user-configured environment override; fall back to the bundled binary
      cmd = Config.engine_cmd || bundled_cmd

      unless File.exist?(cmd)
        raise "Engine executable not found at: #{cmd}"
      end

      run_dir = File.expand_path('../../.run', Config.plugin_root)
      FileUtils.mkdir_p(run_dir)
      log_path = File.join(run_dir, 'engine.log')

      Logger.info('engine_spawning', cmd: cmd, log: log_path)

      @pid = Process.spawn(
        cmd,
        "run-server", # passing CLI argument to start the server
        out: log_path,
        err: [:child, :out],
        pgroup: true
      )
      Process.detach(@pid)
    end
```

---

## 4. Packing the Extension as an `.rbz` File

SketchUp extensions must be distributed as a single `.rbz` file (which is a standard ZIP archive with a renamed extension). 

### File Structure of the `.rbz`
The root of the ZIP archive must contain the top-level loader script and a folder matching the loader's name:

```
planara_extension.rbz/
├── Planara.rb                  # Copied and renamed from loader.rb
└── planara/                    # Copied from planara_plugin/planara/
    ├── boot.rb
    ├── config.rb
    ├── engine_client.rb
    ├── engine_supervisor.rb
    ├── session.rb
    ├── logger.rb
    ├── geometry/
    │   ├── extractor.rb
    │   └── units.rb
    ├── observers/
    │   └── live_validator.rb
    ├── ui/
    │   ├── assets/
    │   │   ├── history.html
    │   │   ├── login.html
    │   │   └── results.html
    │   ├── browser_view.rb
    │   ├── history_dialog.rb
    │   ├── login_dialog.rb
    │   ├── project_picker.rb
    │   └── results_dialog.rb
    └── bin/                    # (Only required for Option B: Local Sidecar)
        ├── darwin/
        │   └── planara-engine
        └── windows/
            └── planara-engine.exe
```

### Automation Script (Mac / Linux)
You can automate building the `.rbz` package with a simple shell script at the project root:

```bash
#!/bin/bash
# build_rbz.sh
set -e

BUILD_DIR="dist"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/planara"

# Copy the top-level registrar and assets
cp planara_plugin/loader.rb "$BUILD_DIR/Planara.rb"
cp -R planara_plugin/planara/ "$BUILD_DIR/planara/"

# If building for Local Sidecar, build and copy compiled binaries
# cp -R binaries/ "$BUILD_DIR/planara/bin/"

# Zip the contents of the build folder
cd "$BUILD_DIR"
zip -r ../Planara-Compliance.rbz Planara.rb planara/
cd ..

echo "Successfully built Planara-Compliance.rbz"
```

---

## 5. Security & Operating System Sandboxing (Local Sidecar Pitfalls)

If you pursue the Local Sidecar strategy, you will hit OS security sandboxing.

### macOS Gatekeeper and Notarization
* **The Problem**: When the Ruby extension runs `Process.spawn` on the compiled `planara-engine` binary, macOS will block it with a popup: *"planara-engine cannot be opened because the developer cannot be verified"*.
* **The Solution**:
  1. Register for an Apple Developer Account.
  2. Code-sign the binary using `codesign`:
     ```bash
     codesign --force --options runtime --sign "Developer ID Application: Your Name (TeamID)" planara-engine
     ```
  3. Zip the binary and submit it to Apple's Notarization Service using `xcrun notarytool`.
  4. Staple the ticket back to the binary using `xcrun stapler staple planara-engine`.

### Windows Defender and Antivirus
* **The Problem**: PyInstaller executables that are unsigned are frequently flagged as false-positives by Windows Defender or third-party antivirus software.
* **The Solution**: 
  - Code-sign the executable using a certificate purchased from a certificate authority (CA) like Sectigo or DigiCert, using the `signtool.exe` utility on Windows.

---

## 6. Native Platform Installers (EXE & DMG)

Instead of delivering an `.rbz` file that the user must manually import inside SketchUp, you can distribute a native system installer (**Windows `.exe`** and **macOS `.dmg`** containing a `.pkg`).

The installer's job is to copy:
1. `Planara.rb` (the registrar)
2. `planara/` (the extension folder, including Python binaries if running Offline Sidecar)

directly into the default SketchUp Plugins folders on the user's system.

### A. Windows Installer (.exe using Inno Setup)
Inno Setup is the industry standard for creating lightweight Windows installers. 

#### Sample Inno Setup Script (`installer.iss`):
```pascal
[Setup]
AppName=Planara Compliance Extension
AppVersion=0.1.0
DefaultDirName={userappdata}\SketchUp
DisableDirPage=yes
DefaultGroupName=Planara
DisableProgramGroupPage=yes
OutputDir=dist-installer
OutputBaseFilename=PlanaraSetup-Win

[Files]
; Copy registrar and plugin folder to all supported SketchUp versions
Source: "dist\Planara.rb"; DestDir: "{userappdata}\SketchUp\SketchUp 2021\SketchUp\Plugins"; Flags: ignoreversion; Check: SketchUpInstalled('2021')
Source: "dist\planara\*"; DestDir: "{userappdata}\SketchUp\SketchUp 2021\SketchUp\Plugins\planara"; Flags: ignoreversion recursesubdirs; Check: SketchUpInstalled('2021')

Source: "dist\Planara.rb"; DestDir: "{userappdata}\SketchUp\SketchUp 2022\SketchUp\Plugins"; Flags: ignoreversion; Check: SketchUpInstalled('2022')
Source: "dist\planara\*"; DestDir: "{userappdata}\SketchUp\SketchUp 2022\SketchUp\Plugins\planara"; Flags: ignoreversion recursesubdirs; Check: SketchUpInstalled('2022')

Source: "dist\Planara.rb"; DestDir: "{userappdata}\SketchUp\SketchUp 2023\SketchUp\Plugins"; Flags: ignoreversion; Check: SketchUpInstalled('2023')
Source: "dist\planara\*"; DestDir: "{userappdata}\SketchUp\SketchUp 2023\SketchUp\Plugins\planara"; Flags: ignoreversion recursesubdirs; Check: SketchUpInstalled('2023')

Source: "dist\Planara.rb"; DestDir: "{userappdata}\SketchUp\SketchUp 2024\SketchUp\Plugins"; Flags: ignoreversion; Check: SketchUpInstalled('2024')
Source: "dist\planara\*"; DestDir: "{userappdata}\SketchUp\SketchUp 2024\SketchUp\Plugins\planara"; Flags: ignoreversion recursesubdirs; Check: SketchUpInstalled('2024')

[Code]
// Helper function to check if the specific SketchUp version directory exists
function SketchUpInstalled(Version: String): Boolean;
begin
  Result := DirExists(ExpandConstant('{userappdata}\SketchUp\SketchUp ' + Version));
end;
```

---

### B. macOS Installer (.dmg / .pkg)
On macOS, distributing a raw folder is prone to user copy errors. Instead, package a standard `.pkg` installer inside a visually branded `.dmg` disk image.

#### 1. Building the PKG Installer
Use macOS command line tools `pkgbuild` and `productbuild`.
Because users have different versions of SketchUp installed, we use a **Postinstall Shell Script** inside the PKG to copy the files to the correct user folders:

```bash
#!/bin/bash
# postinstall.sh - Runs after the PKG copies files to a temp payload directory

# Temp directory where the PKG unpacked Planara
PAYLOAD_DIR="/tmp/planara_payload"
USER_HOME=$(eval echo "~$USER")

# Iterate over all possible SketchUp versions (2020 to 2026)
for year in {2020..2026}; do
    TARGET_DIR="$USER_HOME/Library/Application Support/SketchUp $year/SketchUp/Plugins"
    if [ -d "$TARGET_DIR" ]; then
        echo "Installing Planara to SketchUp $year..."
        cp "$PAYLOAD_DIR/Planara.rb" "$TARGET_DIR/"
        cp -R "$PAYLOAD_DIR/planara" "$TARGET_DIR/"
    fi
done

# Cleanup temp payload
rm -rf "$PAYLOAD_DIR"
exit 0
```

#### 2. Wrapping in a DMG
Use a tool like `dmgbuild` (a python scriptable dmg builder) or **DMG Canvas** to package the PKG installer into a branded DMG with custom background imagery.

---

## 7. Recommended Rollout Strategy

1. **Phase 1 (Beta Testing)**: Set up a **Cloud API** deployment. Distribute a lightweight `.rbz` client (less than 100 KB) to a small group of partner architects. This lets you monitor error rates, verify geometry extraction across different SketchUp versions, and fix bugs instantly on the server.
2. **Phase 2 (Wide Release)**: Keep the Cloud API as the primary mode (enabling teams to collaborate on project history and reports). If a client demands a 100% offline desktop option, offer a separate "Offline Edition" `.rbz` containing the compiled sidecar binaries.
3. **Phase 3 (Enterprise Delivery)**: If targeting large architecture firms with managed workstations, package the selected edition into native **EXE** and **DMG** installers so IT administrators can silently deploy the plugin across their offices.

