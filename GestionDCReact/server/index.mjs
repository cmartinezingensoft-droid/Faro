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
const AI_CONFIG_PATH = path.join(GESTION_DIR, '.app_ai_config.json');
const BAT_PATH = path.join(GESTION_DIR, 'procesar_pendientes.bat');
const DEFAULT_ENTRY_CENTER = Number(process.env.FARO_CENTRO || 0);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const RUN_PENDING_SCRIPT = path.join(__dirname, 'run_pending_integration.py');
const CONFIRM_IMPORTATION_SCRIPT = path.join(__dirname, 'confirm_importation.py');
const DELETE_IMPORTATION_SCRIPT = path.join(__dirname, 'delete_importation.py');
const SAVE_IMPORTATION_SCRIPT = path.join(__dirname, 'save_importation.py');
const LIST_IMPORTATIONS_SCRIPT = path.join(__dirname, 'list_importations.py');
const RETRY_IMPORTATION_DOCUMENT_SCRIPT = path.join(__dirname, 'retry_importation_document.py');
const PERSIST_AI_IMPORTATION_SCRIPT = path.join(__dirname, 'persist_ai_importation.py');

const defaultAiConfig = {
  enabled: false,
  provider: 'openai-compatible',
  endpoint: 'https://api.openai.com/v1/chat/completions',
  model: 'gpt-4o-mini',
  apiKey: '',
  temperature: 0,
  maxTokens: 4000,
  timeoutSeconds: 90,
  prompt: [
    'Extrae de este PDF de proveedor una propuesta de entrada de almacen.',
    'Devuelve solo JSON con cabecera, lineas y totales.',
    'cabecera debe incluir proveedor si aparece, nombre_proveedor, cif, factura, albaran, fecha y fecha_factura.',
    'Cada linea debe incluir referencia_proveedor, descripcion, cantidad, precio, descuento1, iva e importe_origen cuando existan.',
    'No inventes articulos internos; deja articulo vacio si no aparece con claridad.',
  ].join(' '),
};

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

function normalizeAiConfig(value = {}, previous = {}) {
  const next = {
    ...defaultAiConfig,
    ...previous,
    ...value,
  };
  next.enabled = Boolean(next.enabled);
  next.provider = String(next.provider || defaultAiConfig.provider).trim();
  next.endpoint = String(next.endpoint || defaultAiConfig.endpoint).trim();
  next.model = String(next.model || defaultAiConfig.model).trim();
  next.apiKey = value.apiKey === '' && previous.apiKey ? previous.apiKey : String(next.apiKey || '').trim();
  next.temperature = Number.isFinite(Number(next.temperature)) ? Number(next.temperature) : defaultAiConfig.temperature;
  next.maxTokens = Math.max(500, Number.isFinite(Number(next.maxTokens)) ? Number(next.maxTokens) : defaultAiConfig.maxTokens);
  next.timeoutSeconds = Math.max(10, Number.isFinite(Number(next.timeoutSeconds)) ? Number(next.timeoutSeconds) : defaultAiConfig.timeoutSeconds);
  next.prompt = String(next.prompt || defaultAiConfig.prompt);
  return next;
}

function publicAiConfig(config = readAiConfig()) {
  const { apiKey, ...rest } = config;
  return {
    ...rest,
    apiKey: '',
    hasApiKey: Boolean(apiKey),
  };
}

function readAiConfig() {
  try {
    if (!fs.existsSync(AI_CONFIG_PATH)) return { ...defaultAiConfig };
    const parsed = JSON.parse(fs.readFileSync(AI_CONFIG_PATH, 'utf8'));
    return normalizeAiConfig(parsed);
  } catch {
    return { ...defaultAiConfig };
  }
}

function saveAiConfig(payload) {
  ensureDir(GESTION_DIR);
  const current = readAiConfig();
  const next = normalizeAiConfig(payload, current);
  if (!String(payload.apiKey || '').trim() && current.apiKey) {
    next.apiKey = current.apiKey;
  }
  fs.writeFileSync(AI_CONFIG_PATH, JSON.stringify(next, null, 2), 'utf8');
  return publicAiConfig(next);
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
    aiConfig: publicAiConfig(),
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

function parseJsonObjectFromOutput(output) {
  const text = String(output || '');
  for (let start = text.lastIndexOf('{'); start >= 0; start = text.lastIndexOf('{', start - 1)) {
    const candidate = text.slice(start).trim();
    try {
      return JSON.parse(candidate);
    } catch {
      // keep looking for an outer object; BAT wrappers may print lines before JSON
    }
  }
  return null;
}

function unwrapToolResult(result) {
  if (!result || typeof result !== 'object') return result;
  if (result.data && typeof result.data === 'object') {
    return {
      ok: result.ok !== false,
      ...result.data,
      warnings: result.warnings || result.data.warnings,
      meta: result.meta,
    };
  }
  return result;
}

function parseJsonFromText(text) {
  const raw = String(text || '').trim();
  if (!raw) return null;
  const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidate = fenced ? fenced[1].trim() : raw;
  try {
    return JSON.parse(candidate);
  } catch {
    const first = candidate.indexOf('{');
    const last = candidate.lastIndexOf('}');
    if (first >= 0 && last > first) {
      try {
        return JSON.parse(candidate.slice(first, last + 1));
      } catch {
        return null;
      }
    }
  }
  return null;
}

function sha256File(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}

function isPlaceholderValue(value) {
  return /\b(REF00\d+|Producto\s+[A-Z]|Proveedor\s+Ejemplo|F123456|A123456|A12345678)\b/i.test(String(value || ''));
}

function assertNoAiPlaceholders(extracted) {
  const header = extracted && typeof extracted.cabecera === 'object' ? extracted.cabecera : {};
  const lines = Array.isArray(extracted?.lineas) ? extracted.lineas : [];
  const badHeader = Object.values(header).some(isPlaceholderValue);
  const badLine = lines.some((line) => line && typeof line === 'object' && Object.values(line).some(isPlaceholderValue));
  if (badHeader || badLine) {
    throw new Error('La IA devolvio datos de ejemplo (REF001/Producto/Proveedor Ejemplo). No se usara esa propuesta.');
  }
}

function extractBracketArticleCode(description) {
  const match = String(description || '').match(/\[(\d{3,20})\]/);
  return match ? match[1] : '';
}

function extractEan(description) {
  const match = String(description || '').match(/\bEAN\s*:\s*([0-9]{8,14})\b/i);
  return match ? match[1] : '';
}

function normalizeAiLines(lines) {
  return lines.map((line) => {
    const item = line && typeof line === 'object' ? { ...line } : {};
    const bracketCode = extractBracketArticleCode(item.descripcion);
    const ean = extractEan(item.descripcion);
    if (/^\[\d{3,20}\]$/.test(String(item.articulo || '').trim())) {
      item.articulo = String(item.articulo).replace(/[[\]]/g, '');
    }
    if (/^\[\d{3,20}\]$/.test(String(item.referencia_proveedor || '').trim())) {
      item.referencia_proveedor = String(item.referencia_proveedor).replace(/[[\]]/g, '');
    }
    if (bracketCode && !String(item.articulo || '').trim()) item.articulo = bracketCode;
    if (bracketCode && (!String(item.referencia_proveedor || '').trim() || isPlaceholderValue(item.referencia_proveedor))) {
      item.referencia_proveedor = bracketCode;
    }
    if (ean && !String(item.ean || item.codigo_barras || '').trim()) item.ean = ean;
    return item;
  });
}

function normalizeAiHeader(header) {
  const result = header && typeof header === 'object' ? { ...header } : {};
  const proveedor = String(result.proveedor || '').trim();
  if (proveedor && !/^\d+$/.test(proveedor)) {
    if (!String(result.nombre_proveedor || '').trim()) result.nombre_proveedor = proveedor;
    result.proveedor = '';
  }
  return result;
}

function normalizeAiDocument(filePath, extracted, error = '', importacion = null, options = {}) {
  const cabecera = normalizeAiHeader(extracted?.cabecera);
  const missingPolicy = options.missingPolicy === 'fantasma' ? 'fantasma' : 'detener';
  const lineas = normalizeAiLines(Array.isArray(extracted?.lineas) ? extracted.lineas : []);
  const totales = extracted && typeof extracted.totales === 'object' ? extracted.totales : {};
  const hash = fs.existsSync(filePath) ? sha256File(filePath) : '';
  return {
    pdf: filePath,
    pdf_meta: {
      origen: filePath,
      extraction: 'ia',
    },
    estado: 'requiere_revision',
    motivo: error || 'Propuesta generada por IA pendiente de revision',
    cabecera: {
      centro: DEFAULT_ENTRY_CENTER,
      observaciones: 'Entrada propuesta desde IA',
      politica_articulo_no_encontrado: missingPolicy,
      ...cabecera,
    },
    lineas,
    totales,
    validacion: {
      can_create_entry: false,
      ai_generated: true,
      unresolved_lines: lineas.filter((line) => !String(line?.articulo || '').trim()).length,
    },
    advertencias: [
      'Propuesta generada por IA: revisa proveedor, referencias, cantidades, precios e impuestos antes de grabar.',
      'Esta propuesta no crea entrada automaticamente.',
    ],
    incidencias_revision: [
      {
        codigo: 'AI_REVIEW_REQUIRED',
        mensaje: error || 'Revisa la propuesta de IA antes de confirmar manualmente.',
      },
    ],
    importacion: importacion || {
      id: '',
      estado: 'IA_REVISION',
      version: 1,
      hash_sha256: hash,
      persistida: false,
    },
  };
}

function aiProposalFromDocument(document) {
  return {
    pdf: document.pdf_meta,
    hash_sha256: document.importacion?.hash_sha256 || '',
    cabecera: document.cabecera || {},
    lineas: document.lineas || [],
    totales: document.totales || {},
    validacion: document.validacion || {},
    advertencias: document.advertencias || [],
    origen: 'ia',
  };
}

function shortProcessError(error) {
  const stderr = String(error?.stderr || '').trim();
  const stdout = String(error?.stdout || '').trim();
  const message = stderr || stdout || String(error?.message || error);
  const lines = message.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const usefulLine = [...lines].reverse().find((line) => /Error:|Exception:|invalid literal|FaroError/i.test(line)) || lines[0] || 'Error desconocido';
  if (/E2BIG|argument list too long/i.test(message)) {
    return 'La propuesta era demasiado grande para enviarla al proceso de guardado.';
  }
  if (/invalid literal for int\(\).*proveedor|invalid literal for int\(\)/i.test(message)) {
    return 'La IA devolvio el proveedor como texto en lugar de codigo numerico; se ha normalizado para el siguiente intento.';
  }
  return usefulLine.replace(/^Command failed:\s*/i, '').slice(0, 240);
}

function persistAiDocument(document) {
  if (!fs.existsSync(PERSIST_AI_IMPORTATION_SCRIPT)) {
    return {
      ...document,
      importacion: {
        ...(document.importacion || {}),
        persistida: false,
        motivo: `No existe ${path.basename(PERSIST_AI_IMPORTATION_SCRIPT)}`,
      },
      incidencias_revision: [
        ...(document.incidencias_revision || []),
        {
          codigo: 'AI_PROPOSAL_NOT_PERSISTED',
          mensaje: 'La propuesta de IA no se pudo guardar; no se puede confirmar hasta persistirla.',
        },
      ],
    };
  }
  try {
    const output = execFileSync(
      process.env.PYTHON || 'python',
      [PERSIST_AI_IMPORTATION_SCRIPT],
      {
        cwd: __dirname,
        encoding: 'utf8',
        input: JSON.stringify(aiProposalFromDocument(document)),
        maxBuffer: 2_000_000,
        windowsHide: true,
      },
    );
    const persisted = unwrapToolResult(parseJsonObjectFromOutput(output));
    if (persisted?.importacion?.persistida) {
      const validation = persisted.proposal?.validacion || document.validacion || {};
      const ready = validation.can_create_entry !== false;
      return {
        ...document,
        estado: ready ? 'propuesta' : 'requiere_revision',
        motivo: ready ? 'Propuesta generada por IA lista para confirmar' : document.motivo,
        cabecera: persisted.proposal?.cabecera || document.cabecera,
        lineas: persisted.proposal?.lineas || document.lineas,
        totales: persisted.proposal?.totales || document.totales,
        validacion: persisted.proposal?.validacion || document.validacion,
        advertencias: persisted.proposal?.advertencias || document.advertencias,
        incidencias_revision: persisted.proposal?.incidencias_revision || document.incidencias_revision,
        importacion: persisted.importacion,
      };
    }
    if (persisted?.error?.message) {
      throw Object.assign(new Error(String(persisted.error.message)), { stdout: output });
    }
  } catch (error) {
    const message = shortProcessError(error);
    return {
      ...document,
      importacion: {
        ...(document.importacion || {}),
        persistida: false,
        motivo: message,
      },
      incidencias_revision: [
        ...(document.incidencias_revision || []),
        {
          codigo: 'AI_PROPOSAL_NOT_PERSISTED',
          mensaje: `La propuesta de IA no se pudo guardar: ${message}`,
        },
      ],
    };
  }
  return document;
}

function extractPdfTextForAi(filePath) {
  if (path.extname(filePath).toLowerCase() !== '.pdf') return '';
  const script = `
import sys
from pathlib import Path
try:
    from pypdf import PdfReader
    reader = PdfReader(sys.argv[1])
    chunks = []
    for page in reader.pages[:5]:
        chunks.append(page.extract_text() or "")
    print("\\n".join(chunks)[:30000])
except Exception:
    print("")
`;
  try {
    return execFileSync(process.env.PYTHON || 'python', ['-c', script, filePath], {
      cwd: __dirname,
      encoding: 'utf8',
      windowsHide: true,
      maxBuffer: 512_000,
    }).trim();
  } catch {
    return '';
  }
}

function aiImageInputs(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (fileKind(ext) === 'image') {
    return [{ mimeType: contentTypeFor(filePath), data: fs.readFileSync(filePath).toString('base64') }];
  }
  if (ext !== '.pdf') return [];
  ensureDir(PREVIEW_DIR);
  const hash = crypto.createHash('sha1').update(`${filePath}|${fs.statSync(filePath).mtimeMs}|${fs.statSync(filePath).size}|ai`).digest('hex');
  const prefix = path.join(PREVIEW_DIR, `${hash}_page`);
  try {
    execFileSync('pdftoppm', ['-png', '-r', '160', '-f', '1', '-l', '3', filePath, prefix], {
      stdio: 'ignore',
      windowsHide: true,
    });
  } catch {
    return [];
  }
  return fs.readdirSync(PREVIEW_DIR)
    .filter((name) => name.startsWith(`${hash}_page`) && name.endsWith('.png'))
    .sort()
    .slice(0, 3)
    .map((name) => ({ mimeType: 'image/png', data: fs.readFileSync(path.join(PREVIEW_DIR, name)).toString('base64') }));
}

async function callAiForDocument(filePath, config, options = {}) {
  const safePath = assertInsideRoot(filePath);
  const extractedText = extractPdfTextForAi(safePath);
  const imageInputs = aiImageInputs(safePath);
  if (!extractedText && !imageInputs.length) {
    throw new Error('No se pudo preparar texto ni imagenes del documento para IA.');
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), config.timeoutSeconds * 1000);
  try {
    const userContent = [
      {
        type: 'text',
        text: [
          config.prompt,
          '',
          'Reglas obligatorias:',
          '- No inventes valores. Si no ves un dato, dejalo vacio.',
          '- No uses ejemplos ni placeholders como REF001, REF002, Producto A, Producto B o Proveedor Ejemplo.',
          '- Si la descripcion contiene un codigo entre corchetes como [10081], usa ese codigo como articulo y referencia_proveedor si no hay otra referencia clara.',
          '- Si aparece EAN: 8427338100813, devuelve tambien ean con ese valor.',
          '- Devuelve solo JSON valido con cabecera, lineas y totales.',
          '',
          `Nombre de fichero: ${path.basename(safePath)}`,
          extractedText ? `Texto extraido:\n${extractedText}` : 'Texto extraido: no disponible; usa las imagenes adjuntas.',
        ].join('\n'),
      },
      ...imageInputs.map((image) => ({
        type: 'image_url',
        image_url: { url: `data:${image.mimeType};base64,${image.data}` },
      })),
    ];
    const payload = {
      model: config.model,
      temperature: config.temperature,
      max_tokens: config.maxTokens,
      response_format: { type: 'json_object' },
      messages: [
        {
          role: 'system',
          content: 'Eres un extractor de albaranes y facturas de proveedor para entradas de almacen. Responde siempre con JSON valido.',
        },
        {
          role: 'user',
          content: userContent,
        },
      ],
    };
    const headers = { 'content-type': 'application/json' };
    if (config.apiKey) headers.authorization = `Bearer ${config.apiKey}`;
    const response = await fetch(config.endpoint, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const responseText = await response.text();
    if (!response.ok) {
      throw new Error(`IA ${response.status}: ${responseText.slice(0, 600)}`);
    }
    const data = JSON.parse(responseText);
    const content = data?.choices?.[0]?.message?.content || data?.output_text || data?.content || responseText;
    const extracted = typeof content === 'string' ? parseJsonFromText(content) : content;
    if (!extracted || typeof extracted !== 'object') {
      throw new Error('La IA no devolvio JSON utilizable');
    }
    assertNoAiPlaceholders(extracted);
    return persistAiDocument(normalizeAiDocument(safePath, extracted, '', null, options));
  } finally {
    clearTimeout(timeout);
  }
}

async function applyAiFallback(result, payload) {
  if (!payload.aiFallback) return result;
  const config = readAiConfig();
  if (!config.endpoint || !config.model) {
    result.aiFallback = { enabled: false, reason: 'Configura endpoint y modelo antes de procesar con IA.' };
    return result;
  }
  const docs = Array.isArray(result.structuredResult?.documentos) ? result.structuredResult.documentos : [];
  const failed = docs.filter((item) => ['error', 'requiere_revision'].includes(String(item.estado || '')) && item.pdf);
  if (!failed.length) {
    result.aiFallback = { enabled: true, processed: 0 };
    return result;
  }
  const aiDocuments = [];
  const options = { missingPolicy: payload.missingPolicy === 'fantasma' ? 'fantasma' : 'detener' };
  for (const item of failed) {
    try {
      aiDocuments.push(await callAiForDocument(item.pdf, config, options));
    } catch (error) {
      aiDocuments.push(normalizeAiDocument(item.pdf, null, String(error?.message || error), null, options));
    }
  }
  result.structuredResult.documentos = [
    ...docs.filter((item) => !failed.some((failedItem) => failedItem.pdf === item.pdf)),
    ...aiDocuments,
  ];
  result.structuredResult.requiere_revision = result.structuredResult.documentos.filter((item) => item.estado === 'requiere_revision').length;
  result.structuredResult.errores = result.structuredResult.documentos.filter((item) => item.estado === 'error').length;
  result.ok = result.structuredResult.errores === 0 && result.structuredResult.requiere_revision === 0;
  result.aiFallback = { enabled: true, processed: aiDocuments.length };
  return result;
}

async function runAiFallback(payload) {
  const result = payload.result && typeof payload.result === 'object' ? payload.result : null;
  if (!result) throw new Error('Resultado de integracion requerido para aplicar IA');
  return applyAiFallback(result, { aiFallback: true, missingPolicy: payload.missingPolicy });
}

function runIntegration(payload) {
  const modeKey = String(payload.mode || 'entrada');
  const mode = integrationModes[modeKey];
  if (!mode) throw new Error('Modo de integracion no valido');
  if (!fs.existsSync(RUN_PENDING_SCRIPT)) {
    throw new Error(`No existe el lanzador de integracion: ${RUN_PENDING_SCRIPT}`);
  }
  const selectedNames = selectedNamesFromPayload(payload);
  const limit = selectedNames.length ? String(selectedNames.length) : String(payload.limit || '');
  const args = [RUN_PENDING_SCRIPT, mode.missingPolicy, mode.pricePolicy, limit, mode.documentOnly, JSON.stringify(selectedNames)];
  return new Promise((resolve) => {
    const env = {
      ...process.env,
      FARO_BATCH_NOPAUSE: '1',
      FARO_BATCH_NOPOPUP: '1',
    };
    const child = spawn(process.env.PYTHON || 'python', args, {
      cwd: __dirname,
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
    child.on('close', async (code) => {
      const latestLog = listLogs()[0] || null;
      const structuredResult = unwrapToolResult(parseJsonObjectFromOutput(stdout));
      const result = {
        ok: code === 0 && !(structuredResult?.errores > 0) && !(structuredResult?.requiere_revision > 0),
        exitCode: code,
        mode: modeKey,
        modeTitle: mode.title,
        selectedNames,
        stdout,
        stderr,
        structuredResult,
        latestLog,
        state: getState(),
      };
      resolve(await applyAiFallback(result, payload));
    });
    child.on('error', (error) => {
      const structuredResult = unwrapToolResult(parseJsonObjectFromOutput(stdout));
      resolve({
        ok: false,
        exitCode: -1,
        mode: modeKey,
        modeTitle: mode.title,
        selectedNames,
        stdout,
        stderr: stderr + String(error),
        structuredResult,
        latestLog: listLogs()[0] || null,
        state: getState(),
      });
    });
  });
}

function cleanupPendingAfterConfirmation(result, document) {
  if (!result?.ok || result.structuredResult?.pendiente_borrado?.borrado === true) return result;
  const pendingPath = String(document?.pdf || document?.pdf_meta?.origen || '').trim();
  if (!pendingPath) return result;
  const safePath = assertInsideRoot(pendingPath);
  if (!fs.existsSync(safePath) || !fs.statSync(safePath).isFile()) return result;
  if (path.dirname(safePath) !== normalizePath(PENDING_DIR)) return result;

  ensureDir(PROCESSED_DIR);
  const processedPath = uniquePath(PROCESSED_DIR, path.basename(safePath));
  const size = fs.statSync(safePath).size;
  fs.copyFileSync(safePath, processedPath);
  fs.unlinkSync(safePath);

  result.structuredResult = {
    ...(result.structuredResult || {}),
    procesados: {
      ruta: processedPath,
      fichero: path.basename(processedPath),
      bytes: size,
      formato: path.extname(processedPath).slice(1).toLowerCase() || 'file',
      fallback_app: true,
    },
    pendiente_borrado: {
      ruta: safePath,
      bytes: size,
      borrado: true,
      fallback_app: true,
    },
  };
  result.state = getState();
  return result;
}

async function confirmImportation(payload) {
  const result = await runImportationAction(payload, CONFIRM_IMPORTATION_SCRIPT, 'confirmacion');
  if (!result.ok || result.structuredResult?.pendiente_borrado?.borrado === true) return result;
  const propuestaId = String(payload.propuestaId || payload.propuesta_id || '').trim();
  if (!propuestaId) return result;
  const importations = await listImportations({ limit: 200, estados: ['CONFIRMADA', 'PROPUESTA', 'REVISADA', 'IA_REVISION'] });
  const document = importations.structuredResult?.documentos?.find((item) => String(item.importacion?.id || '') === propuestaId);
  return cleanupPendingAfterConfirmation(result, document);
}

function saveImportation(payload) {
  return runImportationAction(payload, SAVE_IMPORTATION_SCRIPT, 'revision');
}

function deleteImportation(payload) {
  return runImportationAction(payload, DELETE_IMPORTATION_SCRIPT, 'borrado');
}

function retryImportationDocument(payload) {
  if (!fs.existsSync(RETRY_IMPORTATION_DOCUMENT_SCRIPT)) {
    throw new Error(`No existe el lanzador de reintento documental: ${RETRY_IMPORTATION_DOCUMENT_SCRIPT}`);
  }
  const propuestaId = String(payload.propuestaId || payload.propuesta_id || '').trim();
  if (!propuestaId) throw new Error('propuestaId es obligatorio');
  const retryPayload = {
    ruta_pdf: payload.rutaPdf || payload.ruta_pdf || '',
    ruta_imagen: payload.rutaImagen || payload.ruta_imagen || '',
    content_base64: payload.contentBase64 || payload.content_base64 || '',
    content_base64_imagen: payload.contentBase64Imagen || payload.content_base64_imagen || '',
    nombre_fichero: payload.nombreFichero || payload.nombre_fichero || '',
    copiar_documentos_entradas: payload.copiarDocumentosEntradas ?? payload.copiar_documentos_entradas ?? true,
  };
  return new Promise((resolve) => {
    const child = spawn(process.env.PYTHON || 'python', [RETRY_IMPORTATION_DOCUMENT_SCRIPT, propuestaId, JSON.stringify(retryPayload)], {
      cwd: __dirname,
      env: process.env,
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
      const structuredResult = unwrapToolResult(parseJsonObjectFromOutput(stdout));
      resolve({
        ok: code === 0 && Boolean(structuredResult?.ok),
        exitCode: code,
        stdout,
        stderr,
        structuredResult,
        state: getState(),
      });
    });
    child.on('error', (error) => {
      const structuredResult = unwrapToolResult(parseJsonObjectFromOutput(stdout));
      resolve({
        ok: false,
        exitCode: -1,
        stdout,
        stderr: stderr + String(error),
        structuredResult,
        state: getState(),
      });
    });
  });
}

function listImportations(payload = {}) {
  if (!fs.existsSync(LIST_IMPORTATIONS_SCRIPT)) {
    throw new Error(`No existe el lanzador de propuestas: ${LIST_IMPORTATIONS_SCRIPT}`);
  }
  const limit = String(payload.limit || 50);
  const offset = String(payload.offset || 0);
  const search = String(payload.search || payload.busqueda || '');
  const estados = JSON.stringify(Array.isArray(payload.estados) ? payload.estados : ['PROPUESTA', 'REVISADA', 'IA_REVISION']);
  return new Promise((resolve) => {
    const child = spawn(process.env.PYTHON || 'python', [LIST_IMPORTATIONS_SCRIPT, limit, estados, offset, search], {
      cwd: __dirname,
      env: process.env,
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
      const structuredResult = unwrapToolResult(parseJsonObjectFromOutput(stdout));
      resolve({
        ok: code === 0 && Boolean(structuredResult?.ok),
        exitCode: code,
        stdout,
        stderr,
        structuredResult,
      });
    });
    child.on('error', (error) => {
      const structuredResult = unwrapToolResult(parseJsonObjectFromOutput(stdout));
      resolve({
        ok: false,
        exitCode: -1,
        stdout,
        stderr: stderr + String(error),
        structuredResult,
      });
    });
  });
}

function runImportationAction(payload, scriptPath, label) {
  if (!fs.existsSync(scriptPath)) {
    throw new Error(`No existe el lanzador de ${label}: ${scriptPath}`);
  }
  const propuestaId = String(payload.propuestaId || payload.propuesta_id || '').trim();
  const version = Number(payload.version || 0);
  const hash = String(payload.hashSha256 || payload.hash_sha256 || '').trim();
  if (!propuestaId || !version || !hash) throw new Error('propuestaId, version y hashSha256 son obligatorios');
  const args = [
    scriptPath,
    propuestaId,
    String(version),
    hash,
    JSON.stringify(payload.cabecera || {}),
    JSON.stringify(Array.isArray(payload.lineas) ? payload.lineas : []),
  ];
  return new Promise((resolve) => {
    const child = spawn(process.env.PYTHON || 'python', args, {
      cwd: __dirname,
      env: process.env,
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
      const structuredResult = unwrapToolResult(parseJsonObjectFromOutput(stdout));
      resolve({
        ok: code === 0 && Boolean(structuredResult?.ok),
        exitCode: code,
        stdout,
        stderr,
        structuredResult,
        state: getState(),
      });
    });
    child.on('error', (error) => {
      const structuredResult = unwrapToolResult(parseJsonObjectFromOutput(stdout));
      resolve({
        ok: false,
        exitCode: -1,
        stdout,
        stderr: stderr + String(error),
        structuredResult,
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

function existingDocumentPath(filePath) {
  const safePath = assertInsideRoot(filePath);
  if (fs.existsSync(safePath) && fs.statSync(safePath).isFile()) return safePath;
  const normalizedPending = normalizePath(PENDING_DIR);
  if (safePath.startsWith(normalizedPending + path.sep)) {
    const processedPath = path.join(PROCESSED_DIR, path.basename(safePath));
    if (fs.existsSync(processedPath) && fs.statSync(processedPath).isFile()) return processedPath;
  }
  return safePath;
}

function servePreview(res, filePath, page = 1) {
  const safePath = existingDocumentPath(filePath);
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
  const safePage = Math.max(1, Number(page || 1));
  const hash = crypto.createHash('sha1').update(`${safePath}|${stat.mtimeMs}|${stat.size}|${safePage}`).digest('hex');
  const prefix = path.join(PREVIEW_DIR, hash);
  const previewPath = `${prefix}.png`;
  if (!fs.existsSync(previewPath)) {
    execFileSync('pdftoppm', ['-png', '-singlefile', '-r', '130', '-f', String(safePage), '-l', String(safePage), safePath, prefix], {
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
    if (req.method === 'GET' && url.pathname === '/api/ai-config') {
      json(res, 200, { ok: true, aiConfig: publicAiConfig() });
      return;
    }
    if (req.method === 'POST' && url.pathname === '/api/ai-config') {
      const payload = await readBody(req);
      json(res, 200, { ok: true, aiConfig: saveAiConfig(payload) });
      return;
    }
    if (req.method === 'GET' && url.pathname === '/api/file') {
      serveFile(res, url.searchParams.get('path') || '');
      return;
    }
    if (req.method === 'GET' && url.pathname === '/api/preview') {
      servePreview(res, url.searchParams.get('path') || '', Number(url.searchParams.get('page') || 1));
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
    if (req.method === 'POST' && url.pathname === '/api/ai-fallback') {
      const payload = await readBody(req);
      const result = await runAiFallback(payload);
      json(res, result.ok ? 200 : 409, result);
      return;
    }
    if (req.method === 'POST' && url.pathname === '/api/confirm-importation') {
      const payload = await readBody(req);
      const result = await confirmImportation(payload);
      json(res, result.ok ? 200 : 409, result);
      return;
    }
    if (req.method === 'POST' && url.pathname === '/api/save-importation') {
      const payload = await readBody(req);
      const result = await saveImportation(payload);
      json(res, result.ok ? 200 : 409, result);
      return;
    }
    if (req.method === 'POST' && url.pathname === '/api/delete-importation') {
      const payload = await readBody(req);
      const result = await deleteImportation(payload);
      json(res, result.ok ? 200 : 409, result);
      return;
    }
    if (req.method === 'POST' && url.pathname === '/api/retry-importation-document') {
      const payload = await readBody(req);
      const result = await retryImportationDocument(payload);
      json(res, result.ok ? 200 : 409, result);
      return;
    }
    if (req.method === 'GET' && url.pathname === '/api/importations') {
      const result = await listImportations({
        limit: Number(url.searchParams.get('limit') || 50),
        offset: Number(url.searchParams.get('offset') || 0),
        search: url.searchParams.get('search') || '',
      });
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
