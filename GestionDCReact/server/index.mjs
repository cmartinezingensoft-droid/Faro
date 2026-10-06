import http from 'node:http';
import { spawn } from 'node:child_process';
import { execFileSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const PORT = Number(process.env.GESTIONDC_API_PORT || 8877);
const MAIN_DIR = process.env.FARO_MAIN_DIR || 'C:\\Proyectos\\Faro';
const GESTION_DIR = path.join(MAIN_DIR, 'GestionDC');
const PENDING_DIR = path.join(GESTION_DIR, 'Pendientes');
const PROCESSED_DIR = path.join(GESTION_DIR, 'Procesados');
const PURCHASES_DIR = path.join(GESTION_DIR, 'Compras');
const LOGS_DIR = path.join(GESTION_DIR, 'Logs');
const HOLD_DIR = path.join(GESTION_DIR, '.app_hold');
const PREVIEW_DIR = path.join(GESTION_DIR, '.app_preview');
const BAT_PATH = path.join(GESTION_DIR, 'procesar_pendientes.bat');

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const integrationModes = {
  documental: {
    title: 'Solo gestion documental',
    missingPolicy: 'detener',
    pricePolicy: 'mantener',
    documentOnly: '1',
  },
  entrada: {
    title: 'Documental + entrada',
    missingPolicy: 'detener',
    pricePolicy: 'mantener',
    documentOnly: '0',
  },
  precios: {
    title: 'Entrada + actualizar precios',
    missingPolicy: 'detener',
    pricePolicy: 'actualizar',
    documentOnly: '0',
  },
  precios_sube: {
    title: 'Entrada + actualizar si sube',
    missingPolicy: 'detener',
    pricePolicy: 'actualizar_si_sube',
    documentOnly: '0',
  },
  fantasma: {
    title: 'Entrada + lineas fantasma',
    missingPolicy: 'fantasma',
    pricePolicy: 'mantener',
    documentOnly: '0',
  },
  fantasma_sube: {
    title: 'Fantasma + actualizar si sube',
    missingPolicy: 'fantasma',
    pricePolicy: 'actualizar_si_sube',
    documentOnly: '0',
  },
};

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function normalizePath(value) {
  return path.resolve(String(value || ''));
}

function assertInsideRoot(filePath) {
  const normalized = normalizePath(filePath);
  const allowedRoots = [GESTION_DIR, path.join(MAIN_DIR, 'Documentos')].map(normalizePath);
  if (!allowedRoots.some((root) => normalized === root || normalized.startsWith(root + path.sep))) {
    throw new Error('Ruta fuera de GestionDC/FARO');
  }
  return normalized;
}

function listFiles(dir, recursive = false, limit = 500) {
  if (!fs.existsSync(dir)) return [];
  const result = [];
  const visit = (current) => {
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const fullPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        if (recursive) visit(fullPath);
        continue;
      }
      const stat = fs.statSync(fullPath);
      result.push(toFileItem(fullPath, stat));
    }
  };
  visit(dir);
  return result
    .sort((a, b) => new Date(b.modifiedAt).getTime() - new Date(a.modifiedAt).getTime())
    .slice(0, limit);
}

function toFileItem(fullPath, stat = fs.statSync(fullPath)) {
  const ext = path.extname(fullPath).toLowerCase();
  const relative = path.relative(GESTION_DIR, fullPath);
  return {
    name: path.basename(fullPath),
    path: fullPath,
    relative,
    extension: ext,
    kind: fileKind(ext),
    size: stat.size,
    modifiedAt: stat.mtime.toISOString(),
    url: `/api/file?path=${encodeURIComponent(fullPath)}`,
  };
}

function fileKind(ext) {
  if (ext === '.pdf') return 'pdf';
  if (['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'].includes(ext)) return 'image';
  if (ext === '.log' || ext === '.txt') return 'text';
  return 'file';
}

function readLog(filePath) {
  const content = fs.readFileSync(filePath, 'utf8');
  const lines = content.split(/\r?\n/).filter(Boolean);
  const summaryLine = [...lines].reverse().find((line) => line.includes('Fin integracion')) || '';
  const cause = extractCause(lines);
  return {
    ...toFileItem(filePath),
    content,
    summaryLine,
    cause,
    status: summaryLine.includes('errores=0') && summaryLine.includes('omitidos=0') ? 'ok' : 'warning',
  };
}

function extractCause(lines) {
  const patterns = [
    /\|\s*ERROR\b/i,
    /Documento omitido/i,
    /ya dado de alta/i,
    /Articulo no encontrado/i,
    /Referencia de proveedor no encontrada/i,
    /FARO_OCR_COMMAND fallo/i,
    /No se pudo/i,
    /\bno encontrado\b/i,
    /pendiente de procesar/i,
  ];
  const causes = lines.filter((line) => patterns.some((pattern) => pattern.test(line)));
  return (causes[0] || lines.at(-1) || '').trim();
}

function listLogs() {
  return listFiles(LOGS_DIR, false, 80).map((item) => {
    try {
      return readLog(item.path);
    } catch {
      return item;
    }
  });
}

function getState() {
  const pending = listFiles(PENDING_DIR, false, 300);
  const processed = listFiles(PROCESSED_DIR, false, 120);
  const documents = listFiles(PURCHASES_DIR, true, 300);
  const logs = listLogs();
  return {
    mainDir: MAIN_DIR,
    gestionDir: GESTION_DIR,
    modes: integrationModes,
    counts: {
      pending: pending.length,
      processed: processed.length,
      documents: documents.length,
      logs: logs.length,
    },
    pending,
    processed,
    documents,
    logs,
  };
}

function json(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
  });
  res.end(body);
}

function text(res, status, payload) {
  res.writeHead(status, { 'content-type': 'text/plain; charset=utf-8' });
  res.end(payload);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk;
      if (body.length > 90_000_000) {
        reject(new Error('Body demasiado grande'));
        req.destroy();
      }
    });
    req.on('end', () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch (error) {
        reject(error);
      }
    });
    req.on('error', reject);
  });
}

function safeUploadName(name) {
  const baseName = path.basename(String(name || '')).replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').trim();
  const ext = path.extname(baseName).toLowerCase();
  const allowed = new Set(['.pdf', '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff']);
  if (!baseName || !allowed.has(ext)) {
    throw new Error(`Tipo de fichero no permitido: ${name}`);
  }
  return baseName;
}

function uniquePendingPath(name) {
  return uniquePath(PENDING_DIR, name);
}

function uniquePath(dir, name) {
  const parsed = path.parse(name);
  let candidate = path.join(dir, name);
  let index = 2;
  while (fs.existsSync(candidate)) {
    candidate = path.join(dir, `${parsed.name}_${index}${parsed.ext}`);
    index += 1;
  }
  return candidate;
}

function uploadPendingFiles(payload) {
  const files = Array.isArray(payload.files) ? payload.files : [];
  if (!files.length) throw new Error('No se recibieron ficheros');
  ensureDir(PENDING_DIR);
  const saved = [];
  for (const file of files) {
    const name = safeUploadName(file.name);
    const data = String(file.data || '');
    if (!data) throw new Error(`Fichero vacio: ${name}`);
    const buffer = Buffer.from(data, 'base64');
    const target = uniquePendingPath(name);
    fs.writeFileSync(target, buffer);
    saved.push(toFileItem(target));
  }
  return saved;
}

function selectedNamesFromPayload(payload) {
  const names = Array.isArray(payload.selectedNames) ? payload.selectedNames : [];
  return names.map((name) => path.basename(String(name))).filter(Boolean);
}

function selectedPendingItems(payload) {
  const selected = new Set(selectedNamesFromPayload(payload).map((name) => name.toLowerCase()));
  if (!selected.size) throw new Error('Selecciona al menos un fichero');
  return listFiles(PENDING_DIR, false, 1000).filter((item) => selected.has(item.name.toLowerCase()));
}

function deletePendingFiles(payload) {
  const items = selectedPendingItems(payload);
  for (const item of items) {
    const safePath = assertInsideRoot(item.path);
    if (path.dirname(safePath) !== normalizePath(PENDING_DIR)) throw new Error('Solo se pueden eliminar pendientes');
    fs.unlinkSync(safePath);
  }
  return items;
}

function archivePendingFiles(payload) {
  const items = selectedPendingItems(payload);
  ensureDir(PROCESSED_DIR);
  const moved = [];
  for (const item of items) {
    const safePath = assertInsideRoot(item.path);
    if (path.dirname(safePath) !== normalizePath(PENDING_DIR)) throw new Error('Solo se pueden archivar pendientes');
    const target = uniquePath(PROCESSED_DIR, item.name);
    fs.renameSync(safePath, target);
    moved.push(toFileItem(target));
  }
  return moved;
}

function generatePdfsFromImages(payload) {
  const items = selectedPendingItems(payload).filter((item) => item.kind === 'image');
  if (!items.length) throw new Error('Selecciona una imagen pendiente para generar PDF');
  const script = `
import sys
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
for i in range(1, len(sys.argv), 2):
    src = sys.argv[i]
    dst = sys.argv[i + 1]
    image = Image.open(src)
    width, height = image.size
    page_w, page_h = A4
    margin = 28
    scale = min((page_w - margin * 2) / width, (page_h - margin * 2) / height)
    draw_w = width * scale
    draw_h = height * scale
    x = (page_w - draw_w) / 2
    y = (page_h - draw_h) / 2
    c = canvas.Canvas(dst, pagesize=A4)
    c.drawImage(src, x, y, draw_w, draw_h, preserveAspectRatio=True, mask='auto')
    c.showPage()
    c.save()
`;
  const args = ['-c', script];
  const generated = [];
  for (const item of items) {
    const target = uniquePendingPath(`${path.parse(item.name).name}.pdf`);
    args.push(item.path, target);
    generated.push(target);
  }
  execFileSync('python', args, { stdio: 'pipe', windowsHide: true });
  return generated.map((filePath) => toFileItem(filePath));
}

function holdUnselectedFiles(selectedNames) {
  if (!selectedNames.length) return [];
  ensureDir(HOLD_DIR);
  const selected = new Set(selectedNames.map((name) => name.toLowerCase()));
  const moved = [];
  for (const item of listFiles(PENDING_DIR, false, 1000)) {
    if (selected.has(item.name.toLowerCase())) continue;
    const target = path.join(HOLD_DIR, `${Date.now()}_${item.name}`);
    fs.renameSync(item.path, target);
    moved.push({ from: item.path, to: target });
  }
  return moved;
}

function restoreHeldFiles(moved) {
  for (const item of [...moved].reverse()) {
    if (fs.existsSync(item.to) && !fs.existsSync(item.from)) {
      fs.renameSync(item.to, item.from);
    }
  }
}

function runIntegration(payload) {
  const modeKey = String(payload.mode || 'entrada');
  const mode = integrationModes[modeKey];
  if (!mode) throw new Error('Modo de integracion no valido');
  if (!fs.existsSync(BAT_PATH)) {
    throw new Error(`No existe el lanzador de integracion: ${BAT_PATH}`);
  }
  const selectedNames = selectedNamesFromPayload(payload);
  const moved = holdUnselectedFiles(selectedNames);
  const limit = selectedNames.length ? String(selectedNames.length) : String(payload.limit || '');
  const args = [mode.missingPolicy, mode.pricePolicy, limit, mode.documentOnly];
  return new Promise((resolve) => {
    const env = {
      ...process.env,
      FARO_BATCH_NOPAUSE: '1',
      FARO_BATCH_NOPOPUP: '1',
    };
    const child = spawn('cmd.exe', ['/c', BAT_PATH, ...args], {
      cwd: GESTION_DIR,
      env,
      windowsHide: true,
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString('utf8');
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString('utf8');
    });
    child.on('close', (code) => {
      restoreHeldFiles(moved);
      const latestLog = listLogs()[0] || null;
      resolve({
        ok: code === 0,
        exitCode: code,
        mode: modeKey,
        modeTitle: mode.title,
        selectedNames,
        stdout,
        stderr,
        latestLog,
        state: getState(),
      });
    });
    child.on('error', (error) => {
      restoreHeldFiles(moved);
      resolve({
        ok: false,
        exitCode: -1,
        mode: modeKey,
        modeTitle: mode.title,
        selectedNames,
        stdout,
        stderr: stderr + String(error),
        latestLog: listLogs()[0] || null,
        state: getState(),
      });
    });
  });
}

function contentTypeFor(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === '.pdf') return 'application/pdf';
  if (ext === '.png') return 'image/png';
  if (ext === '.jpg' || ext === '.jpeg') return 'image/jpeg';
  if (ext === '.webp') return 'image/webp';
  if (ext === '.gif') return 'image/gif';
  if (ext === '.txt' || ext === '.log') return 'text/plain; charset=utf-8';
  return 'application/octet-stream';
}

function serveFile(res, filePath) {
  const safePath = assertInsideRoot(filePath);
  if (!fs.existsSync(safePath) || !fs.statSync(safePath).isFile()) {
    text(res, 404, 'No existe el fichero');
    return;
  }
  res.writeHead(200, {
    'content-type': contentTypeFor(safePath),
    'content-disposition': `inline; filename="${path.basename(safePath).replaceAll('"', '')}"`,
  });
  fs.createReadStream(safePath).pipe(res);
}

function servePreview(res, filePath) {
  const safePath = assertInsideRoot(filePath);
  if (!fs.existsSync(safePath) || !fs.statSync(safePath).isFile()) {
    text(res, 404, 'No existe el fichero');
    return;
  }
  const ext = path.extname(safePath).toLowerCase();
  if (fileKind(ext) === 'image') {
    serveFile(res, safePath);
    return;
  }
  if (ext !== '.pdf') {
    serveFile(res, safePath);
    return;
  }
  ensureDir(PREVIEW_DIR);
  const stat = fs.statSync(safePath);
  const hash = crypto.createHash('sha1').update(`${safePath}|${stat.mtimeMs}|${stat.size}`).digest('hex');
  const prefix = path.join(PREVIEW_DIR, hash);
  const previewPath = `${prefix}.png`;
  if (!fs.existsSync(previewPath)) {
    execFileSync('pdftoppm', ['-png', '-singlefile', '-r', '130', safePath, prefix], {
      stdio: 'ignore',
      windowsHide: true,
    });
  }
  serveFile(res, previewPath);
}

function openFile(filePath) {
  const safePath = assertInsideRoot(filePath);
  if (!fs.existsSync(safePath)) throw new Error('No existe el fichero');
  const stat = fs.statSync(safePath);
  const args = stat.isDirectory()
    ? ['/c', 'start', '', safePath]
    : ['/c', 'explorer.exe', `/select,${safePath}`];
  const child = spawn('cmd.exe', args, {
    detached: true,
    stdio: 'ignore',
    windowsHide: false,
  });
  child.unref();
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url || '/', `http://${req.headers.host || '127.0.0.1'}`);
    if (req.method === 'GET' && url.pathname === '/api/state') {
      json(res, 200, getState());
      return;
    }
    if (req.method === 'GET' && url.pathname === '/api/file') {
      serveFile(res, url.searchParams.get('path') || '');
      return;
    }
    if (req.method === 'GET' && url.pathname === '/api/preview') {
      servePreview(res, url.searchParams.get('path') || '');
      return;
    }
    if (req.method === 'GET' && url.pathname === '/api/log') {
      const filePath = assertInsideRoot(url.searchParams.get('path') || '');
      json(res, 200, readLog(filePath));
      return;
    }
    if (req.method === 'POST' && url.pathname === '/api/run') {
      const payload = await readBody(req);
      const result = await runIntegration(payload);
      json(res, result.ok ? 200 : 409, result);
      return;
    }
    if (req.method === 'POST' && url.pathname === '/api/upload') {
      const payload = await readBody(req);
      const saved = uploadPendingFiles(payload);
      json(res, 200, { ok: true, saved, state: getState() });
      return;
    }
    if (req.method === 'POST' && url.pathname === '/api/delete') {
      const payload = await readBody(req);
      const deleted = deletePendingFiles(payload);
      json(res, 200, { ok: true, deleted, state: getState() });
      return;
    }
    if (req.method === 'POST' && url.pathname === '/api/archive') {
      const payload = await readBody(req);
      const archived = archivePendingFiles(payload);
      json(res, 200, { ok: true, archived, state: getState() });
      return;
    }
    if (req.method === 'POST' && url.pathname === '/api/generate-pdf') {
      const payload = await readBody(req);
      const generated = generatePdfsFromImages(payload);
      json(res, 200, { ok: true, generated, state: getState() });
      return;
    }
    if (req.method === 'POST' && url.pathname === '/api/open') {
      const payload = await readBody(req);
      openFile(payload.path || '');
      json(res, 200, { ok: true });
      return;
    }
    if (url.pathname === '/') {
      text(res, 200, 'GestionDC API OK');
      return;
    }
    text(res, 404, 'No encontrado');
  } catch (error) {
    json(res, 500, { ok: false, error: String(error?.message || error) });
  }
});

ensureDir(PENDING_DIR);
ensureDir(PROCESSED_DIR);
ensureDir(LOGS_DIR);
ensureDir(PREVIEW_DIR);

server.listen(PORT, '127.0.0.1', () => {
  console.log(`GestionDC API en http://127.0.0.1:${PORT}`);
  console.log(`Base: ${GESTION_DIR}`);
  console.log(`Servidor: ${__dirname}`);
});
