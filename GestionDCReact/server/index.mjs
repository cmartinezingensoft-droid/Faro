import http from 'node:http';
import { spawn } from 'node:child_process';
import { runProcess } from './process_runner.mjs';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const PORT = Number(process.env.GESTIONDC_API_PORT || 8877);
const MAIN_DIR = process.env.FARO_MAIN_DIR || 'C:\\Proyectos\\Faro';
const GESTION_DIR = path.resolve(process.env.FARO_GESTION_DC_DIR || path.join(MAIN_DIR, 'GestionDC'));
const DOCUMENTS_DIR = path.resolve(MAIN_DIR, process.env.FARO_DOCUMENTS_DIR || 'Documentos');
const PENDING_DIR = path.join(GESTION_DIR, 'Pendientes');
const PROCESSED_DIR = path.join(GESTION_DIR, 'Procesados');
const PURCHASES_DIR = path.join(GESTION_DIR, 'Compras');
const LOGS_DIR = path.join(GESTION_DIR, 'Logs');
const HOLD_DIR = path.join(GESTION_DIR, '.app_hold');
const PREVIEW_DIR = path.join(GESTION_DIR, '.app_preview');
const PRIVATE_CONFIG_DIR = path.resolve(process.env.GESTIONDC_CONFIG_DIR || path.join(MAIN_DIR, '.GestionDC-private'));
const AI_CONFIG_PATH = path.join(PRIVATE_CONFIG_DIR, 'ai-config.json');
const LOCAL_SESSION_TOKEN = crypto.randomBytes(32).toString('hex');
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
const PREPARE_DOCUMENT_SCRIPT = path.join(__dirname, 'prepare_document.py');
const CREATE_PROVIDERS_SCRIPT = path.join(__dirname, 'create_providers_from_documents.py');

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
  ensureDir(PRIVATE_CONFIG_DIR);
  const current = readAiConfig();
  const next = normalizeAiConfig(payload, current);
  if (!String(payload.apiKey || '').trim() && current.apiKey) {
    next.apiKey = current.apiKey;
  }
  fs.writeFileSync(AI_CONFIG_PATH, JSON.stringify(next, null, 2), { encoding: 'utf8', mode: 0o600 });
  return publicAiConfig(next);
}

function normalizePath(value) {
  return path.resolve(String(value || ''));
}

function assertInsideRoot(filePath) {
  const normalized = normalizePath(filePath);
  const allowedRoots = [GESTION_DIR, DOCUMENTS_DIR].map(normalizePath);
  if (!allowedRoots.some((root) => normalized === root || normalized.startsWith(root + path.sep))) {
    throw new Error('Ruta fuera de GestionDC/FARO');
  }
  const matchingRoot = allowedRoots.find((root) => normalized === root || normalized.startsWith(root + path.sep));
  const relative = path.relative(matchingRoot, normalized);
  if (relative.split(path.sep).some((segment) => segment.startsWith('.'))) throw new Error('Archivo privado');
  if (fs.existsSync(normalized)) {
    const realPath = fs.realpathSync(normalized);
    const realRoot = fs.realpathSync(matchingRoot);
    if (realPath !== realRoot && !realPath.startsWith(realRoot + path.sep)) throw new Error('Ruta enlazada fuera del directorio permitido');
  }
  if (normalized === PRIVATE_CONFIG_DIR || normalized.startsWith(PRIVATE_CONFIG_DIR + path.sep)) throw new Error('Archivo privado');
  return normalized;
}

async function listFiles(dir, recursive = false, limit = 500) {
  const result = [];
  const visit = async (current) => {
    let entries;
    try { entries = await fs.promises.readdir(current, { withFileTypes: true }); }
    catch (error) { if (error.code === 'ENOENT') return; throw error; }
    for (const entry of entries) {
      if (entry.name.startsWith('.') || entry.isSymbolicLink()) continue;
      const fullPath = path.join(current, entry.name);
      if (entry.isDirectory()) { if (recursive) await visit(fullPath); continue; }
      try { result.push(toFileItem(fullPath, await fs.promises.stat(fullPath))); }
      catch (error) { if (error.code !== 'ENOENT') throw error; }
    }
  };
  await visit(dir);
  return result.sort((a, b) => Date.parse(b.modifiedAt) - Date.parse(a.modifiedAt)).slice(0, limit);
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

async function readLog(filePath) {
  const content = await fs.promises.readFile(filePath, 'utf8');
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

async function listLogs() {
  return Promise.all((await listFiles(LOGS_DIR, false, 80)).map(async (item) => {
    try {
      return await readLog(item.path);
    } catch {
      return item;
    }
  }));
}

async function getState() {
  const pending = await listFiles(PENDING_DIR, false, 300);
  const processed = await listFiles(PROCESSED_DIR, false, 120);
  const documents = await listFiles(PURCHASES_DIR, true, 300);
  const logs = await listLogs();
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
    'cache-control': 'no-store',
    'x-content-type-options': 'nosniff',
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

async function selectedPendingItems(payload) {
  const selected = new Set(selectedNamesFromPayload(payload).map((name) => name.toLowerCase()));
  if (!selected.size) throw new Error('Selecciona al menos un fichero');
  return (await listFiles(PENDING_DIR, false, 1000)).filter((item) => selected.has(item.name.toLowerCase()));
}

async function deletePendingFiles(payload) {
  const items = await selectedPendingItems(payload);
  for (const item of items) {
    const safePath = assertInsideRoot(item.path);
    if (path.dirname(safePath) !== normalizePath(PENDING_DIR)) throw new Error('Solo se pueden eliminar pendientes');
    fs.unlinkSync(safePath);
  }
  return items;
}

async function archivePendingFiles(payload) {
  const items = await selectedPendingItems(payload);
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

async function generatePdfsFromImages(payload) {
  const items = (await selectedPendingItems(payload)).filter((item) => item.kind === 'image');
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
  const rendered = await runProcess(process.env.PYTHON || 'python', args, { cwd: __dirname });
  if (rendered.code !== 0) throw new Error(rendered.stderr || 'No se pudo generar el PDF');
  return generated.map((filePath) => toFileItem(filePath));
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
    item.articulo = ''; // Resolved against Faro by the audited backend.
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
  result.proveedor = ''; // Numeric document codes are not trusted ERP provider IDs.
  return result;
}

function normalizeAiDocument(filePath, extracted, error = '', importacion = null, options = {}) {
  const cabecera = normalizeAiHeader(extracted?.cabecera);
  const missingPolicy = options.missingPolicy === 'fantasma' ? 'fantasma' : 'detener';
  const lineas = normalizeAiLines(Array.isArray(extracted?.lineas) ? extracted.lineas : []);
  const totales = extracted && typeof extracted.totales === 'object' ? extracted.totales : {};
  const hash = options.pdfMeta?.hash_sha256 || (fs.existsSync(filePath) ? sha256File(filePath) : '');
  return {
    pdf: filePath,
    pdf_meta: {
      origen: filePath,
      extraction: 'ia',
      page_count: options.pdfMeta?.page_count || 0,
      processed_pages: options.pdfMeta?.processed_pages || [],
      extraction_incomplete: options.pdfMeta?.extraction_incomplete !== false,
    },
    estado: 'requiere_revision',
    motivo: error || 'Propuesta generada por IA pendiente de revision',
    cabecera: {
      observaciones: 'Entrada propuesta desde IA',
      ...cabecera,
      centro: DEFAULT_ENTRY_CENTER,
      politica_articulo_no_encontrado: missingPolicy,
      politica_precio_compra: options.pricePolicy || 'mantener',
      solo_gestion_documental: Boolean(options.documentOnly),
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

async function persistAiDocument(document) {
  try {
    const result = await runPythonScript(PERSIST_AI_IMPORTATION_SCRIPT, { propuesta: aiProposalFromDocument(document) });
    const persisted = result.structuredResult;
    if (!result.ok || !persisted?.importacion?.persistida) throw new Error(persisted?.error?.message || result.stderr || 'No se pudo guardar la propuesta');
    const proposal = persisted.proposal;
    const ready = proposal.validacion?.can_create_entry === true;
    return { ...document, cabecera: proposal.cabecera, lineas: proposal.lineas, totales: proposal.totales,
      pdf_meta: proposal.pdf, validacion: proposal.validacion, advertencias: proposal.advertencias,
      incidencias_revision: proposal.incidencias_revision, importacion: persisted.importacion,
      estado: persisted.importacion.estado === 'CONFIRMADA' ? 'confirmada' : ready ? 'propuesta' : 'requiere_revision',
      motivo: ready ? 'Propuesta de IA validada; pendiente de confirmacion' : 'Revisa las incidencias de la propuesta',
    };
  } catch (error) {
    return { ...document, importacion: { ...document.importacion, persistida: false, motivo: String(error.message || error) },
      incidencias_revision: [{ codigo: 'AI_PROPOSAL_NOT_PERSISTED', mensaje: String(error.message || error) }] };
  }
}

async function prepareDocumentForAi(filePath) {
  const result = await runProcess(process.env.PYTHON || 'python', [PREPARE_DOCUMENT_SCRIPT], {
    cwd: __dirname, input: JSON.stringify({ path: filePath }), maxBytes: 80_000_000,
  });
  const document = parseJsonObjectFromOutput(result.stdout);
  if (result.code !== 0 || document?.error || !document) throw new Error(document?.error || result.stderr || 'No se pudo preparar el documento');
  return document;
}

async function callAiForDocument(filePath, config, options = {}) {
  const safePath = assertInsideRoot(filePath);
  const prepared = await prepareDocumentForAi(safePath);
  const extractedText = prepared.text;
  const imageInputs = prepared.images;
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
          '- Los codigos impresos son referencias del proveedor; no asumas que son articulos internos del ERP.',
          '- Si aparece EAN: 8427338100813, devuelve tambien ean con ese valor.',
          '- Devuelve solo JSON valido con cabecera, lineas y totales. totales debe contener source_gross (total final), source_net y source_tax, como numeros o cadenas decimales.',
          '- No conoces los codigos internos del ERP: cabecera.proveedor debe estar vacio. Identifica al emisor por cif y nombre_proveedor; no confundas sus datos con los del destinatario.',
          '- Cada linea debe incluir cantidad, precio, iva, descuento1 a descuento6 e importe_origen. Conserva todas las apariciones repetidas y su pagina.',
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
    if (data?.choices?.[0]?.finish_reason === 'length') throw new Error('La respuesta de IA se ha truncado; aumenta el limite de salida o divide el documento.');
    if (!Array.isArray(extracted.lineas) || !extracted.cabecera || !extracted.totales) throw new Error('La IA no devolvio cabecera, lineas y totales con el formato requerido');
    assertNoAiPlaceholders(extracted);
    return persistAiDocument(normalizeAiDocument(safePath, extracted, '', null, { ...options, pdfMeta: prepared }));
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
  const mode = integrationModes[payload.mode || result.mode || 'entrada'];
  if (!mode) throw new Error('Modo de IA no valido');
  const options = { missingPolicy: payload.missingPolicy === 'fantasma' ? 'fantasma' : mode.missingPolicy,
    pricePolicy: mode.pricePolicy, documentOnly: mode.documentOnly === '1' };
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
  return applyAiFallback(result, { aiFallback: true, missingPolicy: payload.missingPolicy, mode: payload.mode || result.mode });
}

async function runPythonScript(scriptPath, payload) {
  const output = await runProcess(process.env.PYTHON || 'python', [scriptPath], {
    cwd: __dirname, input: JSON.stringify(payload), timeoutMs: 300_000,
  });
  const structuredResult = unwrapToolResult(parseJsonObjectFromOutput(output.stdout));
  return { ok: output.code === 0 && structuredResult?.ok !== false && Boolean(structuredResult),
    exitCode: output.code, stdout: output.stdout, stderr: output.stderr, structuredResult };
}

async function runIntegration(payload) {
  const modeKey = String(payload.mode || 'entrada');
  const mode = integrationModes[modeKey];
  if (!mode) throw new Error('Modo de integracion no valido');
  const selectedNames = selectedNamesFromPayload(payload);
  if (!selectedNames.length) throw new Error('Selecciona al menos un fichero para integrar');
  const result = await runPythonScript(RUN_PENDING_SCRIPT, {
    politica_articulo_no_encontrado: mode.missingPolicy,
    politica_precio_compra: mode.pricePolicy,
    solo_gestion_documental: mode.documentOnly === '1',
    selected_names: selectedNames, limite: selectedNames.length, persistir_propuesta: true,
  });
  result.ok = result.ok && !(result.structuredResult?.errores > 0) && !(result.structuredResult?.requiere_revision > 0);
  Object.assign(result, { mode: modeKey, modeTitle: mode.title, selectedNames, latestLog: (await listLogs())[0] || null, state: await getState() });
  return applyAiFallback(result, payload);
}

async function cleanupPendingAfterConfirmation(result) {
  if (!result?.ok) return result;
  const pendingPath = String(result.structuredResult?.origen || '').trim();
  const expectedHash = String(result.structuredResult?.importacion?.hash_sha256 || '');
  if (!pendingPath || !expectedHash) return result;
  try {
    const safePath = assertInsideRoot(pendingPath);
    if (!fs.existsSync(safePath) || path.dirname(safePath) !== normalizePath(PENDING_DIR)) return result;
    if (sha256File(safePath) !== expectedHash) throw new Error('El pendiente ha cambiado; se conserva el fichero nuevo');
    ensureDir(PROCESSED_DIR);
    const processedPath = uniquePath(PROCESSED_DIR, path.basename(safePath));
    const size = fs.statSync(safePath).size;
    fs.copyFileSync(safePath, processedPath, fs.constants.COPYFILE_EXCL);
    if (sha256File(processedPath) !== expectedHash || sha256File(safePath) !== expectedHash) throw new Error('No se ha podido verificar la copia; se conserva el pendiente');
    fs.unlinkSync(safePath);
    result.structuredResult.procesados = { ruta: processedPath, fichero: path.basename(processedPath), bytes: size };
    result.structuredResult.pendiente_borrado = { ruta: safePath, borrado: true };
  } catch (error) {
    result.structuredResult.pendiente_borrado = { ruta: pendingPath, borrado: false, error: String(error.message || error) };
  }
  result.state = await getState();
  return result;
}

async function runImportationAction(payload, scriptPath) {
  const propuestaId = String(payload.propuestaId || payload.propuesta_id || '').trim();
  const version = Number(payload.version || 0);
  const hash = String(payload.hashSha256 || payload.hash_sha256 || '').trim();
  if (!propuestaId || !Number.isInteger(version) || version < 1 || !/^[0-9a-f]{64}$/i.test(hash)) throw new Error('Propuesta, version y hash SHA-256 validos son obligatorios');
  const args = { propuesta_id: propuestaId, version, hash_sha256: hash };
  if (scriptPath !== DELETE_IMPORTATION_SCRIPT) {
    if (payload.cabecera !== undefined) args.cabecera = payload.cabecera;
    if (payload.lineas !== undefined) args.lineas = payload.lineas;
  }
  const result = await runPythonScript(scriptPath, args);
  result.state = await getState();
  return result;
}

async function confirmImportation(payload) {
  return cleanupPendingAfterConfirmation(await runImportationAction(payload, CONFIRM_IMPORTATION_SCRIPT));
}
function saveImportation(payload) { return runImportationAction(payload, SAVE_IMPORTATION_SCRIPT); }
function deleteImportation(payload) { return runImportationAction(payload, DELETE_IMPORTATION_SCRIPT); }

async function retryImportationDocument(payload) {
  const propuestaId = String(payload.propuestaId || payload.propuesta_id || '').trim();
  if (!propuestaId) throw new Error('propuestaId es obligatorio');
  const args = { propuesta_id: propuestaId, copiar_documentos_entradas: true };
  for (const [source, target] of [['rutaPdf', 'ruta_pdf'], ['rutaImagen', 'ruta_imagen']]) {
    if (payload[source] || payload[target]) args[target] = assertInsideRoot(payload[source] || payload[target]);
  }
  const result = await runPythonScript(RETRY_IMPORTATION_DOCUMENT_SCRIPT, args);
  result.state = await getState();
  return result;
}

async function listImportations(payload = {}) {
  const allowed = new Set(['PROPUESTA', 'REVISADA', 'CONFIRMADA', 'DOCUMENTADA']);
  const estados = Array.isArray(payload.estados) ? payload.estados : ['PROPUESTA', 'REVISADA'];
  if (!estados.length || estados.some((state) => !allowed.has(state))) throw new Error('Estado de revision no valido');
  return runPythonScript(LIST_IMPORTATIONS_SCRIPT, {
    limite: Math.min(200, Math.max(1, Number(payload.limit || 25))),
    offset: Math.max(0, Number(payload.offset || 0)), busqueda: String(payload.search || ''), estados,
  });
}

async function createProvidersFromDocuments(payload = {}) {
  const documents = Array.isArray(payload.documentos) ? payload.documentos : [];
  if (!documents.length) throw new Error('No hay proveedores pendientes de alta');
  const result = await runPythonScript(CREATE_PROVIDERS_SCRIPT, { documentos: documents });
  result.state = await getState();
  return result;
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

function serveFile(res, filePath, privatePreview = false) {
  const safePath = privatePreview ? normalizePath(filePath) : assertInsideRoot(filePath);
  if (privatePreview && (path.dirname(safePath) !== normalizePath(PREVIEW_DIR) || !/^[a-f0-9]{40}\.png$/.test(path.basename(safePath)))) throw new Error('Vista previa no valida');
  if (!fs.existsSync(safePath) || !fs.statSync(safePath).isFile()) {
    text(res, 404, 'No existe el fichero');
    return;
  }
  res.writeHead(200, {
    'content-type': contentTypeFor(safePath),
    'x-content-type-options': 'nosniff',
    'cache-control': 'no-store',
    'content-disposition': `inline; filename="${path.basename(safePath).replaceAll('"', '')}"`,
  });
  const stream = fs.createReadStream(safePath);
  stream.on('error', () => res.destroy());
  stream.pipe(res);
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

async function servePreview(res, filePath, page = 1) {
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
  const safePage = Number(page);
  if (!Number.isInteger(safePage) || safePage < 1) throw new Error('Pagina no valida');
  const hash = crypto.createHash('sha1').update(`${safePath}|${stat.mtimeMs}|${stat.size}|${safePage}`).digest('hex');
  const prefix = path.join(PREVIEW_DIR, hash);
  const previewPath = `${prefix}.png`;
  if (!fs.existsSync(previewPath)) {
    const result = await runProcess(process.env.PYTHON || 'python', [PREPARE_DOCUMENT_SCRIPT], {
      cwd: __dirname, input: JSON.stringify({ path: safePath, preview: true, page: safePage, output: previewPath }),
    });
    if (result.code !== 0) throw new Error(parseJsonObjectFromOutput(result.stdout)?.error || 'No se pudo renderizar el PDF');
  }
  serveFile(res, previewPath, true);
}

function openFile(filePath) {
  const safePath = assertInsideRoot(filePath);
  if (!fs.existsSync(safePath)) throw new Error('No existe el fichero');
  const stat = fs.statSync(safePath);
  if (process.platform !== 'win32') throw new Error('Abrir en el explorador requiere Windows');
  const args = stat.isDirectory() ? [safePath] : [`/select,${safePath}`];
  const child = spawn('explorer.exe', args, { detached: true, stdio: 'ignore', windowsHide: false });
  child.on('error', () => {});
  child.unref();
}

function validateLocalRequest(req) {
  const devPorts = new Set(['5173', '5174', ...(process.env.GESTIONDC_DEV_PORTS || '').split(',').map((port) => port.trim()).filter(Boolean)]);
  const expectedHosts = new Set([`127.0.0.1:${PORT}`, `localhost:${PORT}`]);
  for (const port of devPorts) {
    expectedHosts.add(`127.0.0.1:${port}`);
    expectedHosts.add(`localhost:${port}`);
  }
  if (!expectedHosts.has(String(req.headers.host || '').toLowerCase())) throw Object.assign(new Error('Host no permitido'), { status: 403 });
  if (req.headers.origin) {
    const origin = new URL(String(req.headers.origin));
    if (origin.protocol !== 'http:' || !expectedHosts.has(origin.host.toLowerCase())) throw Object.assign(new Error('Origen no permitido'), { status: 403 });
  }
  if (!['GET', 'HEAD'].includes(req.method)) {
    if (String(req.headers['content-type'] || '').split(';')[0] !== 'application/json') throw Object.assign(new Error('Se requiere application/json'), { status: 415 });
    const token = String(req.headers['x-gdc-token'] || '');
    if (token.length !== LOCAL_SESSION_TOKEN.length || !crypto.timingSafeEqual(Buffer.from(token), Buffer.from(LOCAL_SESSION_TOKEN))) throw Object.assign(new Error('Sesion no valida; recarga la aplicacion'), { status: 403 });
  }
}

const server = http.createServer(async (req, res) => {
  try {
    validateLocalRequest(req);
    const url = new URL(req.url || '/', `http://${req.headers.host || '127.0.0.1'}`);
    if (req.method === 'GET' && url.pathname === '/api/session') {
      json(res, 200, { token: LOCAL_SESSION_TOKEN });
      return;
    }
    if (req.method === 'GET' && url.pathname === '/api/state') {
      json(res, 200, await getState());
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
      await servePreview(res, url.searchParams.get('path') || '', Number(url.searchParams.get('page') || 1));
      return;
    }
    if (req.method === 'GET' && url.pathname === '/api/log') {
      const filePath = assertInsideRoot(url.searchParams.get('path') || '');
      json(res, 200, await readLog(filePath));
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
    if (req.method === 'POST' && url.pathname === '/api/providers/create-from-documents') {
      const payload = await readBody(req);
      const result = await createProvidersFromDocuments(payload);
      json(res, result.ok ? 200 : 409, result);
      return;
    }
    if (req.method === 'GET' && url.pathname === '/api/importations') {
      const result = await listImportations({
        limit: Number(url.searchParams.get('limit') || 50),
        offset: Number(url.searchParams.get('offset') || 0),
        search: url.searchParams.get('search') || '',
        estados: (url.searchParams.get('estados') || 'PROPUESTA,REVISADA').split(','),
      });
      json(res, result.ok ? 200 : 409, result);
      return;
    }
    if (req.method === 'POST' && url.pathname === '/api/upload') {
      const payload = await readBody(req);
      const saved = uploadPendingFiles(payload);
      json(res, 200, { ok: true, saved, state: await getState() });
      return;
    }
    if (req.method === 'POST' && url.pathname === '/api/delete') {
      const payload = await readBody(req);
      const deleted = await deletePendingFiles(payload);
      json(res, 200, { ok: true, deleted, state: await getState() });
      return;
    }
    if (req.method === 'POST' && url.pathname === '/api/archive') {
      const payload = await readBody(req);
      const archived = await archivePendingFiles(payload);
      json(res, 200, { ok: true, archived, state: await getState() });
      return;
    }
    if (req.method === 'POST' && url.pathname === '/api/generate-pdf') {
      const payload = await readBody(req);
      const generated = await generatePdfsFromImages(payload);
      json(res, 200, { ok: true, generated, state: await getState() });
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
    if (!res.headersSent) json(res, error.status || 500, { ok: false, error: String(error?.message || error) });
    else res.destroy();
  }
});

ensureDir(PRIVATE_CONFIG_DIR);
const legacyAiConfig = path.join(GESTION_DIR, '.app_ai_config.json');
if (fs.existsSync(legacyAiConfig)) {
  if (!fs.existsSync(AI_CONFIG_PATH)) {
    const value = fs.readFileSync(legacyAiConfig);
    fs.writeFileSync(AI_CONFIG_PATH, value, { mode: 0o600, flag: 'wx' });
  }
  else {
    const backup = path.join(PRIVATE_CONFIG_DIR, `legacy-ai-config-${Date.now()}.json`);
    fs.writeFileSync(backup, fs.readFileSync(legacyAiConfig), { mode: 0o600, flag: 'wx' });
  }
  fs.unlinkSync(legacyAiConfig);
}
ensureDir(PENDING_DIR);
ensureDir(PROCESSED_DIR);
ensureDir(LOGS_DIR);
ensureDir(PREVIEW_DIR);

server.listen(PORT, '127.0.0.1', () => {
  console.log(`GestionDC API en http://127.0.0.1:${PORT}`);
  console.log(`Base: ${GESTION_DIR}`);
  console.log(`Servidor: ${__dirname}`);
});
