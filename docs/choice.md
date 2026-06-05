# Packaging Planara for End Users

Yes, this can absolutely be done! To make the plugin usable by architects who don't have Python or development tools installed, we need to completely bundle the Python `planara_engine` and package it alongside the SketchUp Ruby plugin.

## Open Questions

Before we build the automation for this, we have two approaches for the final artifact the architect receives. Which one do you prefer?

> [!IMPORTANT]
> **Option A: The Standard SketchUp Way (`.rbz` file) - (Recommended)**
> We use PyInstaller to compile the Python engine into standalone binaries for Windows and Mac, and we place them *inside* the plugin folder. We then package everything into a single `Planara.rbz` file. 
> - **Architect experience:** They open SketchUp -> Extension Manager -> Install Extension -> select the `.rbz` file. 
> - **Pros:** This is the standard way all SketchUp plugins are installed. It doesn't trigger overzealous antivirus alerts as often as `.exe` files do, and it doesn't require administrator privileges to install.

> [!IMPORTANT]
> **Option B: Standalone Installers (`.exe` for Windows, `.pkg`/`.dmg` for macOS)**
> We create custom setup wizards that the architect double-clicks to install.
> - **Architect experience:** They double-click `InstallPlanara.exe` or open a `.dmg` and run a `.pkg` installer. The installer automatically copies the plugin files into their SketchUp Plugins folder.
> - **Pros:** Familiar "double-click to install" experience for non-technical users. 
> - **Cons:** Requires detecting which versions of SketchUp they have installed. Executables often get flagged by Windows SmartScreen unless you pay for a code signing certificate.

*Please let me know which option you prefer, and we can proceed with the build scripts!*

---

## Proposed Implementation Plan (Assuming Option A)

If you choose Option A, here is how we will automate the build process:

### 1. Bundle the Python Engine
We will add PyInstaller to the `planara_engine` project. PyInstaller analyzes the Python code and packages the interpreter, the FastAPI app, Shapely, and all other dependencies into a single, standalone executable (no Python installation required by the architect).
- On Windows, this creates `planara_engine.exe`.
- On macOS, this creates a Unix executable `planara_engine`.

### 2. Update the Ruby Supervisor
We will modify `planara_plugin/planara/engine_supervisor.rb` to:
- Detect the operating system (Windows vs. macOS).
- Look for the bundled PyInstaller executable inside the plugin's `bin/` directory.
- Execute it directly, eliminating the need for `pipx` or virtual environments.

#### [MODIFY] [engine_supervisor.rb](file:///Users/jagadishsunilpednekar/Planara-Plugin/planara_plugin/planara/engine_supervisor.rb)
Update the start logic to locate the correct platform-specific binary.

### 3. Create a Build Script
We will create a build script (`build.sh` / `build.bat` or a Python script) that:
1. Compiles the Python engine using PyInstaller.
2. Copies the resulting binaries into `planara_plugin/bin/`.
3. Zips the `planara_plugin` folder and `loader.rb` into `Planara.rbz`.

*(If you choose Option B, the build script will instead use **Inno Setup** on Windows and **pkgbuild** on macOS to generate the `.exe` and `.dmg` installers).*

## Verification Plan
1. Compile the engine locally.
2. Manually test running the compiled binary to ensure all Python dependencies (like Shapely and FastAPI) were included correctly.
3. Package the plugin and install it via the target method (either `.rbz` or the installer).
4. Launch SketchUp and verify that the plugin successfully starts the sidecar and can validate a model.
