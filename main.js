// main.js (modified for frameless window and IPC handlers)
const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');

function createWindow(){
  const win = new BrowserWindow({
    width: 1100,
    height: 750,
    frame: false,    // Disable default frame to use custom controls
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    }
  });
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  // IPC event handlers for window controls
  ipcMain.on('minimize', () => { win.minimize(); });
  ipcMain.on('maximize', () => { 
      if (win.isMaximized()) { win.unmaximize(); }
      else { win.maximize(); }
  });
  ipcMain.on('close', () => { win.close(); });
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
