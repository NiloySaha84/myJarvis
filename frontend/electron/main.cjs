const { app, BrowserWindow, dialog } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");

const BACKEND_HOST = "127.0.0.1";
const BACKEND_PORT = 8000;
const BACKEND_URL = `http://${BACKEND_HOST}:${BACKEND_PORT}`;

let mainWindow;
let backendProcess;
let startedBackend = false;
let logFilePath;

function writeLog(message) {
  const line = `[${new Date().toISOString()}] ${message}\n`;
  console.log(message);

  if (!logFilePath) return;

  try {
    fs.appendFileSync(logFilePath, line);
  } catch {
    // don't crash the app if log write fails
  }
}

function getLogFilePath() {
  const logDir = path.join(os.homedir(), "Library", "Logs", "MyJarvis");
  fs.mkdirSync(logDir, { recursive: true });
  return path.join(logDir, "electron.log");
}

function getBackendDirectory() {
  if (process.env.JARVIS_BACKEND_DIR) {
    return process.env.JARVIS_BACKEND_DIR;
  }

  if (app.isPackaged) {
    const bundledBackend = path.join(process.resourcesPath, "backend");

    try {
      fs.accessSync(path.join(bundledBackend, "server.py"));
      return bundledBackend;
    } catch {
      writeLog(`Bundled backend not found at ${bundledBackend}`);
    }
  }

  return path.resolve(__dirname, "..", "..");
}

function getBackendPath(uvPath) {
  const uvDirectory = path.dirname(uvPath);
  const uvPathEntry = uvDirectory && uvDirectory !== "." ? `${uvDirectory}:` : "";
  return `${uvPathEntry}/opt/homebrew/bin:/usr/local/bin:${process.env.PATH || ""}`;
}

function checkBackendHealth(timeoutMs = 1000) {
  return new Promise((resolve) => {
    const request = http.get(`${BACKEND_URL}/health`, { timeout: timeoutMs }, (response) => {
      response.resume();
      resolve(response.statusCode >= 200 && response.statusCode < 500);
    });

    request.on("timeout", () => {
      request.destroy();
      resolve(false);
    });
    request.on("error", () => resolve(false));
  });
}

async function waitForBackend(maxAttempts = 30) {
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (await checkBackendHealth(1000)) {
      return true;
    }

    await new Promise((resolve) => setTimeout(resolve, 500));
  }

  return false;
}

async function startBackend() {
  if (await checkBackendHealth()) {
    return;
  }

  const backendDirectory = getBackendDirectory();
  const uvPath = process.env.JARVIS_UV_PATH || "uv";
  const command =
    process.env.JARVIS_BACKEND_COMMAND ||
    `"${uvPath}" run uvicorn server:app --host ${BACKEND_HOST} --port ${BACKEND_PORT}`;

  writeLog(`Backend directory: ${backendDirectory}`);
  writeLog(`Backend command: ${command}`);

  backendProcess = spawn("zsh", ["-lc", command], {
    cwd: backendDirectory,
    env: {
      ...process.env,
      PATH: getBackendPath(uvPath),
      PYTHONUNBUFFERED: "1",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  startedBackend = true;

  backendProcess.stdout.on("data", (data) => {
    writeLog(`[Jarvis backend] ${data.toString().trim()}`);
  });

  backendProcess.stderr.on("data", (data) => {
    writeLog(`[Jarvis backend] ${data.toString().trim()}`);
  });

  backendProcess.on("exit", (code) => {
    writeLog(`[Jarvis backend] exited with code ${code}`);
    backendProcess = null;
  });
}

function stopBackend() {
  if (startedBackend && backendProcess && !backendProcess.killed) {
    backendProcess.kill("SIGTERM");
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1100,
    minHeight: 740,
    title: "MyJarvis",
    backgroundColor: "#030711",
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
  });

  mainWindow.webContents.on("did-fail-load", (event, code, description) => {
    writeLog(`Window failed to load: ${code} ${description}`);
  });

  const indexPath = path.join(__dirname, "..", "dist", "index.html");
  writeLog(`Loading UI: ${indexPath}`);
  mainWindow.loadFile(indexPath);
}

app.whenReady().then(async () => {
  logFilePath = getLogFilePath();
  writeLog("MyJarvis Electron starting.");

  createWindow();
  await startBackend();

  const ready = await waitForBackend();
  if (!ready) {
    dialog.showMessageBox(mainWindow, {
      type: "warning",
      title: "Jarvis Backend Not Ready",
      message: "The desktop app opened, but the Python backend did not respond yet.",
      detail:
        `Make sure uv is installed and your API keys are available. Log file: ${logFilePath}`,
    });
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  stopBackend();
});
