import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  ClipboardCheck,
  Columns3,
  Database,
  Eye,
  FileImage,
  FilePlus2,
  FileText,
  ListFilter,
  FolderOpen,
  History,
  Image as ImageIcon,
  Loader2,
  Maximize2,
  RefreshCw,
  Search,
  Square,
  SquareCheck,
  Trash2,
  Upload,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

type FileKind = 'pdf' | 'image' | 'text' | 'file';

type FileItem = {
  name: string;
  path: string;
  relative: string;
  extension: string;
  kind: FileKind;
  size: number;
  modifiedAt: string;
  url: string;
};

type LogItem = FileItem & {
  content?: string;
  summaryLine?: string;
  cause?: string;
  status?: 'ok' | 'warning';
};

type Mode = {
  title: string;
  missingPolicy: string;
  pricePolicy: string;
  documentOnly: string;
};

type AppState = {
  mainDir: string;
  gestionDir: string;
  modes: Record<string, Mode>;
  counts: {
    pending: number;
    processed: number;
    documents: number;
    logs: number;
  };
  pending: FileItem[];
  processed: FileItem[];
  documents: FileItem[];
  logs: LogItem[];
};

type RunResult = {
  ok: boolean;
  exitCode: number;
  mode: string;
  modeTitle: string;
  selectedNames: string[];
  stdout: string;
  stderr: string;
  latestLog?: LogItem | null;
  state?: AppState;
};

type UploadResult = {
  ok: boolean;
  saved: FileItem[];
  state: AppState;
};

type ActionResult = {
  ok: boolean;
  state: AppState;
  deleted?: FileItem[];
  archived?: FileItem[];
  generated?: FileItem[];
};

type ProcessOptions = {
  documentOnly: boolean;
  updatePrices: boolean;
  updateOnlyIfUp: boolean;
  ghostLines: boolean;
};

type Notice = {
  title: string;
  message: string;
  details?: string[];
  variant?: 'info' | 'warning';
};

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('es-ES', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}

function fileIcon(kind: FileKind, size = 32) {
  if (kind === 'image') return <FileImage size={size} />;
  if (kind === 'pdf') return <FileText size={size} />;
  return <FileText size={size} />;
}

function modeFromOptions(options: ProcessOptions) {
  if (options.documentOnly) return 'documental';
  if (options.ghostLines && options.updateOnlyIfUp) return 'fantasma_sube';
  if (options.ghostLines) return 'fantasma';
  if (options.updateOnlyIfUp) return 'precios_sube';
  if (options.updatePrices) return 'precios';
  return 'entrada';
}

function logMessage(line: string) {
  return line.includes('|') ? line.split('|').slice(1).join('|').trim() : line.trim();
}

function isGhostArticleLine(line: string) {
  return /(Articulo no encontrado|Linea fantasma generada)/i.test(line) && /linea_fantasma=True/i.test(line);
}

function logHasIncidents(log?: LogItem | null) {
  const content = log?.content || '';
  const messages = content.split(/\r?\n/).map(logMessage).filter(Boolean);
  const finalLine = messages.find((line) => line.startsWith('Fin integracion'));
  const finalMatch = finalLine?.match(/omitidos=(\d+)\s+errores=(\d+)/i);
  if (finalMatch && (Number(finalMatch[1]) > 0 || Number(finalMatch[2]) > 0)) return true;
  if (messages.some((line) => !isGhostArticleLine(line) && /\bERROR\b|Documento omitido|ya dado de alta|Proveedor no encontrado|Articulo no encontrado|No se pudo/i.test(line))) {
    return true;
  }
  return log?.status === 'warning';
}

function runHasIncidents(result: RunResult) {
  return !result.ok || logHasIncidents(result.latestLog);
}

function incidentMessage(result: RunResult) {
  const content = result.latestLog?.content || '';
  const messages = content.split(/\r?\n/).map(logMessage).filter(Boolean);
  const cause = messages.find((line) => !isGhostArticleLine(line) && /\bERROR\b|Proveedor no encontrado|Articulo no encontrado|Documento omitido|ya dado de alta|No se pudo/i.test(line));
  return cause || result.latestLog?.cause || result.latestLog?.summaryLine || result.stderr || 'La integracion ha finalizado con incidencias.';
}

function highlightedNoticeMessage(message: string) {
  const parts = message.split(/(Proveedor no encontrado|Articulo no encontrado|Artículo no encontrado)/i);
  return parts.map((part, index) => (
    /Proveedor no encontrado|Articulo no encontrado|Artículo no encontrado/i.test(part)
      ? <span className="noticeErrorText" key={`${part}-${index}`}>{part}</span>
      : part
  ));
}

function integrationReport(result: RunResult) {
  const content = result.latestLog?.content || '';
  const messages = content.split(/\r?\n/).map(logMessage).filter(Boolean);
  const details: string[] = [];
  const finalLine = messages.find((line) => line.startsWith('Fin integracion'));
  const finalMatch = finalLine?.match(/total=(\d+)\s+procesados_ok=(\d+)\s+documentados=(\d+)\s+omitidos=(\d+)\s+errores=(\d+)/i);
  const isDocumentOnly = finalMatch ? Number(finalMatch[3]) > 0 && Number(finalMatch[2]) === 0 : result.mode === 'documental';
  if (finalMatch) {
    if (isDocumentOnly) {
      details.push(`Documentos detectados: ${finalMatch[1]}`);
      details.push(`Guardados en DOCUMENTO: ${finalMatch[3]}`);
      details.push('Entrada de almacen: no creada');
      details.push('Movimientos de stock: no generados');
      details.push(`Errores: ${finalMatch[5]}`);
    } else {
      details.push(`Documentos detectados: ${finalMatch[1]}`);
      details.push(`Procesados correctamente: ${finalMatch[2]}`);
      details.push(`Solo documentados: ${finalMatch[3]}`);
      details.push(`Omitidos: ${finalMatch[4]}`);
      details.push(`Errores: ${finalMatch[5]}`);
    }
  }

  if (isDocumentOnly) {
    if (!details.length && finalLine) details.push(finalLine);
    return details;
  }

  const lineCount = messages
    .map((line) => line.match(/Documento cabecera .*?\slineas=(\d+)/i)?.[1])
    .filter(Boolean)
    .reduce((total, value) => total + Number(value), 0);
  if (lineCount) details.push(`Articulos/lineas detectadas: ${lineCount}`);

  const entries = messages
    .map((line) => line.match(/Documento procesado entrada centro=(\d+)\s+ejercicio=(\d+)\s+serie=([A-Z0-9]+)\s+numero=(\d+)/i))
    .filter((match): match is RegExpMatchArray => Boolean(match))
    .map((match) => `${match[2]}-${match[3]}-${match[4]}`);
  if (entries.length) details.push(`Entradas generadas: ${entries.join(', ')}`);

  const gdCopies = messages.filter((line) => line.startsWith('Documento copiado GestionDC=')).length;
  const entryCopies = messages.filter((line) => line.startsWith('Documento copiado DocumentosEntradas=')).length;
  const processedCopies = messages.filter((line) => line.startsWith('Documento copiado Procesados=')).length;
  const deletedPending = messages.filter((line) => line.startsWith('Documento borrado Pendientes=')).length;
  if (gdCopies) details.push(`Copias en GestionDC: ${gdCopies}`);
  if (entryCopies) details.push(`Copias en Documentos/Entradas: ${entryCopies}`);
  if (processedCopies) details.push(`Copias en Procesados: ${processedCopies}`);
  if (deletedPending) details.push(`Borrados de Pendientes: ${deletedPending}`);

  const ghostArticles = messages.filter(isGhostArticleLine);
  if (ghostArticles.length) {
    details.push(`Lineas fantasma generadas: ${ghostArticles.length}`);
    ghostArticles.slice(0, 4).forEach((line) => details.push(line.replace(/Articulo no encontrado/i, 'Linea fantasma generada')));
  }

  const missingArticles = messages.filter((line) => /Articulo no encontrado/i.test(line) && !isGhostArticleLine(line));
  if (missingArticles.length) {
    details.push(`Articulos no encontrados: ${missingArticles.length}`);
    missingArticles.slice(0, 4).forEach((line) => details.push(line));
  }

  const priceUpdates = messages.filter((line) => /precio/i.test(line) && /actualiz|variad|cambio/i.test(line));
  if (priceUpdates.length) {
    details.push(`Precios actualizados: ${priceUpdates.length}`);
    priceUpdates.slice(0, 4).forEach((line) => details.push(line));
  } else {
    details.push('Precios actualizados: 0');
  }

  if (!details.length && finalLine) details.push(finalLine);
  return details;
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const payload = await response.json();
  if (!response.ok) {
    throw Object.assign(new Error(payload.error || 'Error de servidor'), { payload });
  }
  return payload as T;
}

async function fileToBase64(file: File) {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

function ToolbarButton({
  icon,
  label,
  active,
  disabled,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <button className={`toolButton ${active ? 'active' : ''}`} type="button" disabled={disabled} onClick={onClick} title={label}>
      <span>{icon}</span>
      <strong>{label}</strong>
    </button>
  );
}

function Preview({ file, zoom }: { file?: FileItem; zoom: number }) {
  if (!file) {
    return (
      <div className="emptyPreview">
        <Eye size={42} />
        <strong>Selecciona o arrastra documentos</strong>
        <span>PDFs e imagenes se muestran aqui antes de integrarse.</span>
      </div>
    );
  }
  if (file.kind === 'pdf') {
    return (
      <div className="imagePreview pdfPreview">
        <img src={`/api/preview?path=${encodeURIComponent(file.path)}`} alt={file.name} style={{ width: `${zoom}%` }} />
      </div>
    );
  }
  if (file.kind === 'image') {
    return (
      <div className="imagePreview">
        <img src={file.url} alt={file.name} style={{ width: `${zoom}%` }} />
      </div>
    );
  }
  return <iframe className="previewFrame" src={file.url} title={file.name} />;
}

function PendingTile({
  file,
  active,
  selected,
  onOpen,
  onToggle,
}: {
  file: FileItem;
  active: boolean;
  selected: boolean;
  onOpen: () => void;
  onToggle: () => void;
}) {
  return (
    <button className={`pendingTile ${active ? 'active' : ''} ${selected ? 'selected' : ''}`} type="button" onClick={onOpen}>
      <span
        className="tileCheck"
        onClick={(event) => {
          event.stopPropagation();
          onToggle();
        }}
        title={selected ? 'Quitar de la seleccion' : 'Seleccionar'}
      >
        {selected ? <SquareCheck size={17} /> : <Square size={17} />}
      </span>
      <span className={`docIcon ${file.kind}`}>
        {file.kind === 'pdf' ? <strong>PDF</strong> : fileIcon(file.kind, 38)}
      </span>
      <strong>{file.name}</strong>
      <small>{formatBytes(file.size)} · {formatDate(file.modifiedAt)}</small>
    </button>
  );
}

function PendingTable({
  files,
  activeFile,
  selectedNames,
  onOpen,
  onToggle,
}: {
  files: FileItem[];
  activeFile?: FileItem;
  selectedNames: Set<string>;
  onOpen: (file: FileItem) => void;
  onToggle: (file: FileItem) => void;
}) {
  return (
    <div className="pendingTable">
      <div className="tableHead">
        <span />
        <span>Fichero</span>
        <span>Tipo</span>
        <span>Tamano</span>
        <span>Fecha</span>
      </div>
      {files.map((file) => (
        <button className={`tableRow ${activeFile?.path === file.path ? 'active' : ''}`} type="button" key={file.path} onClick={() => onOpen(file)}>
          <span
            onClick={(event) => {
              event.stopPropagation();
              onToggle(file);
            }}
          >
            {selectedNames.has(file.name) ? <SquareCheck size={16} /> : <Square size={16} />}
          </span>
          <strong>{file.name}</strong>
          <small>{file.extension.replace('.', '').toUpperCase()}</small>
          <small>{formatBytes(file.size)}</small>
          <small>{formatDate(file.modifiedAt)}</small>
        </button>
      ))}
    </div>
  );
}

function logEventType(message: string) {
  if (isGhostArticleLine(message)) return 'ghost';
  if (/ERROR|no encontrado|incidencia/i.test(message)) return 'error';
  if (/Documento procesado entrada/i.test(message)) return 'entry';
  if (/Articulo|lineas=|precio/i.test(message)) return 'article';
  return 'info';
}

function logEvents(log?: LogItem) {
  return (log?.content || '')
    .split(/\r?\n/)
    .map((line) => {
      const [stamp, ...rest] = line.split('|');
      const message = rest.join('|').trim();
      return { stamp: stamp.trim(), message, type: logEventType(message) };
    })
    .filter((event) => event.message)
    .filter((event) => (
      event.type === 'entry'
      || event.type === 'article'
      || event.type === 'ghost'
      || event.type === 'error'
      || event.message.startsWith('Fin integracion')
    ));
}

function logStats(log?: LogItem) {
  const events = logEvents(log);
  const summary = events.find((event) => event.message.startsWith('Fin integracion'))?.message || '';
  const finalMatch = summary.match(/total=(\d+)\s+procesados_ok=(\d+)\s+documentados=(\d+)\s+omitidos=(\d+)\s+errores=(\d+)/i);
  const documented = finalMatch ? Number(finalMatch[3]) : 0;
  const ok = finalMatch ? Number(finalMatch[2]) : 0;
  const documentOnly = documented > 0 && ok === 0;
  const entries = events.filter((event) => event.type === 'entry').length;
  const articles = documentOnly ? 0 : events
    .map((event) => event.message.match(/lineas=(\d+)/i)?.[1])
    .filter(Boolean)
    .reduce((total, value) => total + Number(value), 0);
  const ghostArticles = documentOnly ? 0 : events.filter((event) => event.type === 'ghost').length;
  const missingArticles = documentOnly ? 0 : events.filter((event) => /Articulo no encontrado/i.test(event.message) && event.type !== 'ghost').length;
  const priceUpdates = documentOnly ? 0 : events.filter((event) => /precio/i.test(event.message) && /actualiz|variad|cambio/i.test(event.message)).length;
  const errors = finalMatch ? Number(finalMatch[5]) : events.filter((event) => event.type === 'error').length;
  return {
    total: finalMatch ? Number(finalMatch[1]) : 0,
    ok,
    documented,
    omitted: finalMatch ? Number(finalMatch[4]) : 0,
    errors,
    entries,
    articles,
    missingArticles,
    ghostArticles,
    priceUpdates,
    documentOnly,
  };
}

function processedFilesFromLog(log?: LogItem) {
  const lines = (log?.content || '').split(/\r?\n/).map(logMessage).filter(Boolean);
  return lines
    .map((line) => line.match(/^Documento copiado Procesados=(.+)$/i)?.[1]?.trim())
    .filter((value): value is string => Boolean(value))
    .map((filePath) => ({
      path: filePath,
      name: filePath.split(/[\\/]/).pop() || filePath,
      url: `/api/file?path=${encodeURIComponent(filePath)}`,
    }));
}

function dateInputValue(value: string) {
  return value ? new Date(value).toISOString().slice(0, 10) : '';
}

function LogPanel({ logs, activeLog, onSelect }: { logs: LogItem[]; activeLog?: LogItem; onSelect: (log: LogItem) => void }) {
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const filteredLogs = useMemo(() => logs.filter((log) => {
    const day = dateInputValue(log.modifiedAt);
    if (dateFrom && day < dateFrom) return false;
    if (dateTo && day > dateTo) return false;
    return true;
  }), [logs, dateFrom, dateTo]);
  const selectedLog = activeLog && filteredLogs.some((log) => log.path === activeLog.path) ? activeLog : filteredLogs[0];
  const stats = logStats(selectedLog);
  const events = stats.documentOnly
    ? logEvents(selectedLog).filter((event) => event.message.startsWith('Fin integracion'))
    : logEvents(selectedLog);
  const processedFiles = processedFilesFromLog(selectedLog);
  return (
    <section className="panel logsPanel">
      <header className="panelHeader compactHeader logsHeader">
        <div>
          <span className="eyebrow">Historico</span>
          <h2>Logs de integracion</h2>
        </div>
        <div className="logFilters">
          <label>
            Desde
            <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
          </label>
          <label>
            Hasta
            <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
          </label>
          <button type="button" onClick={() => { setDateFrom(''); setDateTo(''); }}>
            Limpiar
          </button>
        </div>
        <History size={20} />
      </header>
      <div className="logsDashboard">
        <div className="logCards">
          {filteredLogs.map((log) => {
            const itemStats = logStats(log);
            return (
            <button
              key={log.path}
              className={`logCard ${log.status === 'ok' ? 'ok' : 'warning'} ${selectedLog?.path === log.path ? 'active' : ''}`}
              type="button"
              onClick={() => onSelect(log)}
            >
              <span className="logCardIcon">{log.status === 'ok' ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}</span>
              <strong>{log.name}</strong>
              <small>{formatDate(log.modifiedAt)}</small>
              <div className="logMetricLine">
                {itemStats.documentOnly ? (
                  <span className="softTag document">DOCUMENTO {itemStats.documented}</span>
                ) : (
                  <>
                    <span className="softTag entry">Entradas {itemStats.entries}</span>
                    <span className="softTag article">Articulos {itemStats.articles}</span>
                    {!!itemStats.ghostArticles && <span className="softTag ghost">Fantasmas {itemStats.ghostArticles}</span>}
                    <span className="softTag price">Precios {itemStats.priceUpdates}</span>
                    <span className="softTag missing">No encontrados {itemStats.missingArticles}</span>
                  </>
                )}
                <span className="softTag error">Errores {itemStats.errors}</span>
              </div>
              <p>{log.cause || log.summaryLine || 'Sin resumen'}</p>
            </button>
          );})}
          {!filteredLogs.length && <div className="mutedBox">No hay logs para el filtro indicado.</div>}
        </div>
        <div className="logDetailGrid">
          <section className={`logSummaryGrid ${stats.documentOnly ? 'documentOnly' : ''}`}>
            {stats.documentOnly ? (
              <>
                <div className="summaryTile document"><span>DOCUMENTO</span><strong>{stats.documented}</strong></div>
                <div className="summaryTile entry neutral"><span>Entradas almacen</span><strong>0</strong></div>
                <div className="summaryTile article neutral"><span>Articulos</span><strong>0</strong></div>
                <div className="summaryTile warning"><span>Omitidos</span><strong>{stats.omitted}</strong></div>
                <div className="summaryTile error"><span>Errores</span><strong>{stats.errors}</strong></div>
              </>
            ) : (
              <>
                <div className="summaryTile entry"><span>Entradas</span><strong>{stats.entries}</strong></div>
                <div className="summaryTile article"><span>Articulos</span><strong>{stats.articles}</strong></div>
                <div className="summaryTile ghost"><span>Fantasmas</span><strong>{stats.ghostArticles}</strong></div>
                <div className="summaryTile price"><span>Precios act.</span><strong>{stats.priceUpdates}</strong></div>
                <div className="summaryTile missing"><span>No encontrados</span><strong>{stats.missingArticles}</strong></div>
                <div className="summaryTile warning"><span>Omitidos</span><strong>{stats.omitted}</strong></div>
                <div className="summaryTile error"><span>Errores</span><strong>{stats.errors}</strong></div>
              </>
            )}
          </section>
          <section className="processedFilesPanel">
            <span>Ficheros procesados</span>
            <div>
              {processedFiles.map((file) => (
                <a href={file.url} target="_blank" rel="noreferrer" key={file.path} title={file.path}>
                  <FileText size={14} />
                  {file.name}
                </a>
              ))}
              {!processedFiles.length && <small>No hay ficheros procesados asociados a este log.</small>}
            </div>
          </section>
          <section className="eventGrid">
            {stats.documentOnly && (
              <article className="eventCard document">
                <span>Solo gestion documental</span>
                <strong>Documento guardado</strong>
                <p>El PDF se ha integrado en DOCUMENTO/GestionDC. No se ha creado entrada de almacen, no se han generado movimientos de stock y no se han tratado articulos.</p>
              </article>
            )}
            {events.map((event, index) => (
              <article className={`eventCard ${event.type}`} key={`${event.stamp}-${index}`}>
                <span>{event.stamp}</span>
                <strong>{event.type === 'entry' ? 'Entrada generada' : event.type === 'article' ? 'Articulo' : event.type === 'ghost' ? 'Linea fantasma' : event.type === 'error' ? 'Incidencia' : 'Resumen'}</strong>
                <p>{event.type === 'ghost' ? event.message.replace(/Articulo no encontrado/i, 'Linea fantasma generada') : event.message}</p>
              </article>
            ))}
            {!events.length && <div className="mutedBox">Selecciona un log para ver su detalle.</div>}
          </section>
        </div>
      </div>
    </section>
  );
}

function HistoryPanel({ processed, documents, columnsView }: { processed: FileItem[]; documents: FileItem[]; columnsView: boolean }) {
  const [archiveSearch, setArchiveSearch] = useState('');
  const [nameFilterOpen, setNameFilterOpen] = useState(false);
  const [nameFilter, setNameFilter] = useState('');
  const [activeArchivePath, setActiveArchivePath] = useState('');
  const [archiveZoom, setArchiveZoom] = useState(82);
  const [sortKey, setSortKey] = useState<'name' | 'size' | 'date'>('date');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');
  const files = useMemo(() => {
    const query = archiveSearch.trim().toLowerCase();
    const nameQuery = nameFilter.trim().toLowerCase();
    return [...processed, ...documents]
      .filter((file) => !query || `${file.name} ${file.relative}`.toLowerCase().includes(query))
      .filter((file) => !nameQuery || file.name.toLowerCase().includes(nameQuery))
      .sort((a, b) => {
        let result = 0;
        if (sortKey === 'name') result = a.name.localeCompare(b.name, 'es', { numeric: true, sensitivity: 'base' });
        if (sortKey === 'size') result = a.size - b.size;
        if (sortKey === 'date') result = new Date(a.modifiedAt).getTime() - new Date(b.modifiedAt).getTime();
        return sortDirection === 'asc' ? result : -result;
      });
  }, [processed, documents, archiveSearch, nameFilter, sortKey, sortDirection]);
  function changeSort(nextKey: 'name' | 'size' | 'date') {
    if (sortKey === nextKey) {
      setSortDirection((current) => (current === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortKey(nextKey);
    setSortDirection(nextKey === 'name' ? 'asc' : 'desc');
  }
  const sortMark = (key: 'name' | 'size' | 'date') => sortKey === key ? (sortDirection === 'asc' ? ' ▲' : ' ▼') : '';
  const activeArchiveFile = files.find((file) => file.path === activeArchivePath) || files[0];
  useEffect(() => {
    setActiveArchivePath((current) => files.find((file) => file.path === current)?.path || files[0]?.path || '');
  }, [files]);
  const processedCount = files.filter((file) => file.relative.toLowerCase().startsWith('procesados')).length;
  const gestionCount = files.length - processedCount;
  return (
    <section className={`panel historyPanel ${columnsView ? 'details' : 'icons'}`}>
      <header className="panelHeader compactHeader archiveHeader">
        <div>
          <span className="eyebrow">Archivo</span>
          <h2>Procesados y GestionDC</h2>
        </div>
        <div className="archiveSearch">
          <Search size={15} />
          <input value={archiveSearch} onChange={(event) => setArchiveSearch(event.target.value)} placeholder="Buscar documento" />
        </div>
        <Archive size={20} />
      </header>
      <div className="archiveStatus">
        <span><strong>{files.length}</strong> documentos</span>
        <span>{processedCount} procesados</span>
        <span>{gestionCount} GestionDC</span>
        <div className="archiveSortControls">
          <span>Ordenar por</span>
          <button type="button" className={sortKey === 'name' ? 'active' : ''} onClick={() => changeSort('name')}>Nombre{sortMark('name')}</button>
          <button type="button" className={sortKey === 'size' ? 'active' : ''} onClick={() => changeSort('size')}>Tamano{sortMark('size')}</button>
          <button type="button" className={sortKey === 'date' ? 'active' : ''} onClick={() => changeSort('date')}>Fecha{sortMark('date')}</button>
        </div>
        <div className="archiveAutoFilter">
          <button
            type="button"
            className={nameFilterOpen || nameFilter ? 'active' : ''}
            onClick={() => setNameFilterOpen((current) => !current)}
            title="Autofiltro por nombre"
          >
            <ListFilter size={14} />
            Autofiltro
          </button>
          {nameFilterOpen && (
            <input
              value={nameFilter}
              onChange={(event) => setNameFilter(event.target.value)}
              placeholder="Nombre..."
              autoFocus
            />
          )}
          {nameFilter && (
            <button type="button" onClick={() => setNameFilter('')} title="Limpiar autofiltro">
              Limpiar
            </button>
          )}
        </div>
      </div>
      <div className="archiveBody">
        <div className="archiveMain">
          {columnsView ? (
            <div className="archiveTable">
              <div className="archiveTableHead">
                <button type="button" onClick={() => changeSort('name')}>Nombre{sortMark('name')}</button>
                <span>Ubicacion</span>
                <span>Tipo</span>
                <button type="button" onClick={() => changeSort('size')}>Tamano{sortMark('size')}</button>
                <button type="button" onClick={() => changeSort('date')}>Fecha{sortMark('date')}</button>
              </div>
              {files.map((file) => (
                <button
                  type="button"
                  className={`archiveTableRow ${activeArchiveFile?.path === file.path ? 'active' : ''}`}
                  key={`${file.path}-${file.modifiedAt}`}
                  onClick={() => setActiveArchivePath(file.path)}
                >
                  <strong>{file.name}</strong>
                  <small>{file.relative}</small>
                  <small>{file.extension.replace('.', '').toUpperCase() || 'FILE'}</small>
                  <small>{formatBytes(file.size)}</small>
                  <small>{formatDate(file.modifiedAt)}</small>
                </button>
              ))}
              {!files.length && <div className="mutedBox">No hay documentos visibles.</div>}
            </div>
          ) : (
            <div className="archiveExplorer">
              {files.map((file) => (
                <button
                  type="button"
                  className={`archiveTile ${activeArchiveFile?.path === file.path ? 'active' : ''}`}
                  key={`${file.path}-${file.modifiedAt}`}
                  title={file.relative}
                  onClick={() => setActiveArchivePath(file.path)}
                >
                  <span className={`docIcon ${file.kind}`}>
                    {file.kind === 'pdf' ? <strong>PDF</strong> : fileIcon(file.kind, 38)}
                  </span>
                  <strong>{file.name}</strong>
                  <small>{file.relative}</small>
                  <em>{formatBytes(file.size)} · {formatDate(file.modifiedAt)}</em>
                </button>
              ))}
              {!files.length && <div className="mutedBox">No hay documentos visibles.</div>}
            </div>
          )}
        </div>
        <section className="viewerDesk archiveViewer">
          <div className="viewerTools">
            <span>{activeArchiveFile?.name || 'Sin documento'}</span>
            <input className="zoomSlider" type="range" min="55" max="160" value={archiveZoom} onChange={(event) => setArchiveZoom(Number(event.target.value))} aria-label="Zoom archivo" />
            {activeArchiveFile && (
              <a className="smallButton" href={activeArchiveFile.url} target="_blank" rel="noreferrer">
                <Maximize2 size={15} /> Abrir
              </a>
            )}
          </div>
          <Preview file={activeArchiveFile} zoom={archiveZoom} />
        </section>
      </div>
    </section>
  );
}

export default function App() {
  const [state, setState] = useState<AppState | null>(null);
  const [activeFilePath, setActiveFilePath] = useState('');
  const [selectedNames, setSelectedNames] = useState<Set<string>>(new Set());
  const [processOptions, setProcessOptions] = useState<ProcessOptions>({
    documentOnly: false,
    updatePrices: false,
    updateOnlyIfUp: false,
    ghostLines: false,
  });
  const [activeLog, setActiveLog] = useState<LogItem | undefined>();
  const [search, setSearch] = useState('');
  const [running, setRunning] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [zoom, setZoom] = useState(82);
  const [columnsView, setColumnsView] = useState(false);
  const [mainTab, setMainTab] = useState<'principal' | 'logs' | 'archivo'>('principal');
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState<Notice | null>(null);

  async function refresh() {
    const next = await requestJson<AppState>('/api/state');
    setState(next);
    setActiveFilePath((current) => current || next.pending[0]?.path || '');
    setActiveLog((current) => current || next.logs[0]);
    setSelectedNames((current) => {
      const available = new Set(next.pending.map((file) => file.name));
      return new Set([...current].filter((name) => available.has(name)));
    });
  }

  useEffect(() => {
    refresh().catch((err) => setError(String(err.message || err)));
  }, []);

  const pending = useMemo(() => {
    const files = state?.pending || [];
    const query = search.trim().toLowerCase();
    if (!query) return files;
    return files.filter((file) => `${file.name} ${file.relative}`.toLowerCase().includes(query));
  }, [state, search]);

  const activeFile = useMemo(() => state?.pending.find((file) => file.path === activeFilePath) || pending[0], [state, activeFilePath, pending]);
  const selectedCount = selectedNames.size;
  const allVisibleSelected = pending.length > 0 && pending.every((file) => selectedNames.has(file.name));

  function toggleFile(file: FileItem) {
    setSelectedNames((current) => {
      const next = new Set(current);
      if (next.has(file.name)) next.delete(file.name);
      else next.add(file.name);
      return next;
    });
  }

  function toggleAllVisible() {
    setSelectedNames((current) => {
      const next = new Set(current);
      if (allVisibleSelected) pending.forEach((file) => next.delete(file.name));
      else pending.forEach((file) => next.add(file.name));
      return next;
    });
  }

  function actionNames() {
    if (selectedCount) return [...selectedNames];
    if (activeFile) return [activeFile.name];
    return [];
  }

  function applyStateAfterAction(next: AppState) {
    setState(next);
    setSelectedNames(new Set());
    setActiveFilePath((current) => next.pending.find((file) => file.path === current)?.path || next.pending[0]?.path || '');
  }

  async function runPendingAction(endpoint: '/api/delete' | '/api/archive' | '/api/generate-pdf', success: (result: ActionResult) => string) {
    const names = actionNames();
    if (!names.length) {
      setError('Selecciona un fichero pendiente.');
      return;
    }
    setError('');
    setMessage('');
    const result = await requestJson<ActionResult>(endpoint, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ selectedNames: names }),
    });
    applyStateAfterAction(result.state);
    setMessage(success(result));
  }

  async function deletePendingAction() {
    const names = actionNames();
    if (!names.length) {
      setError('Selecciona un fichero pendiente.');
      return;
    }
    const label = names.length === 1 ? `el fichero "${names[0]}"` : `${names.length} ficheros`;
    if (!window.confirm(`¿Desea borrar ${label} de Pendientes?`)) return;
    await runPendingAction('/api/delete', (result) => `${result.deleted?.length || 0} fichero(s) eliminado(s)`);
  }

  async function loadLog(log: LogItem) {
    const full = await requestJson<LogItem>(`/api/log?path=${encodeURIComponent(log.path)}`);
    setActiveLog(full);
    setMainTab('logs');
  }

  async function uploadFiles(files: FileList | File[]) {
    const valid = [...files].filter((file) => /\.(pdf|png|jpe?g|webp|bmp|tiff?)$/i.test(file.name));
    if (!valid.length) {
      setError('Arrastra PDFs o imagenes validas.');
      return;
    }
    setUploading(true);
    setError('');
    setMessage('');
    try {
      const payload = {
        files: await Promise.all(valid.map(async (file) => ({ name: file.name, data: await fileToBase64(file) }))),
      };
      const result = await requestJson<UploadResult>('/api/upload', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setState(result.state);
      setActiveFilePath(result.saved[0]?.path || result.state.pending[0]?.path || '');
      setMessage(`${result.saved.length} fichero(s) copiado(s) a Pendientes`);
    } catch (err: any) {
      setError(String(err.message || err));
    } finally {
      setUploading(false);
      setDragging(false);
    }
  }

  async function openPath(pathToOpen: string) {
    await requestJson('/api/open', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ path: pathToOpen }),
    });
  }

  async function runIntegration() {
    if (!state) return;
    if (!selectedCount) {
      setNotice({
        title: 'Seleccion necesaria',
        message: 'Debe seleccionar al menos un fichero para procesar.',
      });
      return;
    }
    setRunning(true);
    setError('');
    setMessage('');
    setRunResult(null);
    const activeMode = modeFromOptions(processOptions);
    const names = [...selectedNames];
    try {
      const result = await requestJson<RunResult>('/api/run', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ mode: activeMode, selectedNames: names }),
      });
      setRunResult(result);
      if (result.state) setState(result.state);
      if (result.latestLog) setActiveLog(result.latestLog);
      if (runHasIncidents(result)) {
        setNotice({
          title: 'Integracion con incidencias',
          message: incidentMessage(result),
          details: integrationReport(result),
          variant: 'warning',
        });
      } else {
        setNotice({
          title: 'Integracion finalizada',
          message: 'El proceso se ha completado correctamente.',
          details: integrationReport(result),
          variant: 'info',
        });
      }
      setSelectedNames(new Set());
      setActiveFilePath(result.state?.pending[0]?.path || '');
    } catch (err: any) {
      const payload = err.payload as RunResult | undefined;
      if (payload) {
        setRunResult(payload);
        if (payload.state) setState(payload.state);
        if (payload.latestLog) setActiveLog(payload.latestLog);
        setNotice({
          title: 'Integracion con incidencias',
          message: payload.latestLog?.cause || payload.latestLog?.summaryLine || payload.stderr || 'La integracion ha finalizado con incidencias.',
          details: integrationReport(payload),
          variant: 'warning',
        });
      } else {
        const message = String(err.message || err);
        setError(message);
        setNotice({
          title: 'Error de integracion',
          message,
          variant: 'warning',
        });
      }
    } finally {
      setRunning(false);
    }
  }

  if (!state) {
    return (
      <div className="loading">
        <Loader2 className="spin" />
        <span>Cargando GestionDC...</span>
        {error && <strong>{error}</strong>}
      </div>
    );
  }

  return (
    <main
      className={`appShell ${dragging ? 'dragging' : ''}`}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(event) => {
        if (event.currentTarget === event.target) setDragging(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        uploadFiles(event.dataTransfer.files);
      }}
    >
      <nav className="menuBar">
        <span>Fichero</span>
        <span>Edicion</span>
        <span>Imagen</span>
        <span>Ver</span>
        <span>Orden</span>
        <span>Columnas</span>
      </nav>

      <nav className="mainTabs">
        <button className={mainTab === 'principal' ? 'active' : ''} type="button" onClick={() => setMainTab('principal')}>
          Principal
        </button>
        <button className={mainTab === 'logs' ? 'active' : ''} type="button" onClick={() => setMainTab('logs')}>
          Logs de integracion
        </button>
        <button className={mainTab === 'archivo' ? 'active' : ''} type="button" onClick={() => setMainTab('archivo')}>
          Procesados/documentos
        </button>
      </nav>

      <header className="toolBar">
        <div className="toolGroup primaryGroup">
          <ToolbarButton icon={running ? <Loader2 className="spin" size={32} /> : <ClipboardCheck size={32} />} label="Procesar" disabled={running || state.pending.length === 0} onClick={runIntegration} />
        </div>
        <div className="toolGroup editGroup">
          <ToolbarButton icon={<Trash2 size={32} />} label="Eliminar" disabled={!activeFile} onClick={() => deletePendingAction().catch((err) => setError(String(err.message || err)))} />
          <ToolbarButton icon={<FilePlus2 size={32} />} label="Generar PDF" disabled={!activeFile} onClick={() => runPendingAction('/api/generate-pdf', (result) => `${result.generated?.length || 0} PDF(s) generado(s)`).catch((err) => setError(String(err.message || err)))} />
          <ToolbarButton icon={<Archive size={32} />} label="Archivar" disabled={!activeFile} onClick={() => runPendingAction('/api/archive', (result) => `${result.archived?.length || 0} fichero(s) archivado(s)`).catch((err) => setError(String(err.message || err)))} />
        </div>
        <div className="toolGroup viewGroup">
          <ToolbarButton icon={<ImageIcon size={32} />} label="Iconos Grandes" active={!columnsView} onClick={() => setColumnsView(false)} />
          <ToolbarButton icon={<Columns3 size={32} />} label="Detalles" active={columnsView} onClick={() => setColumnsView(true)} />
          <ToolbarButton icon={<FolderOpen size={32} />} label="Abrir Directorio" onClick={() => openPath(`${state.gestionDir}\\Pendientes`).catch((err) => setError(String(err.message || err)))} />
          <ToolbarButton icon={<RefreshCw size={32} />} label="Refrescar" onClick={() => refresh()} />
        </div>
      </header>

      <section className="statusStrip">
        <strong>{state.counts.pending}</strong> pendientes
        <span><Database size={15} /> {state.counts.documents} GestionDC</span>
        <span><FolderOpen size={15} /> {state.counts.processed} procesados</span>
        <span><History size={15} /> {state.counts.logs} logs</span>
        <em>{state.gestionDir}</em>
      </section>

      {mainTab === 'principal' && (
      <section className="documentDesk">
        <aside className="processPanel">
          <section className="integrateDesk">
            <header>
              <span className="eyebrow">Parametros</span>
              <h2>Opciones</h2>
            </header>
            <div className="optionList">
              <label className="checkOption">
                <input
                  type="checkbox"
                  checked={processOptions.documentOnly}
                  onChange={(event) => setProcessOptions((current) => ({
                    ...current,
                    documentOnly: event.target.checked,
                    updatePrices: event.target.checked ? false : current.updatePrices,
                    updateOnlyIfUp: event.target.checked ? false : current.updateOnlyIfUp,
                    ghostLines: event.target.checked ? false : current.ghostLines,
                  }))}
                />
                <span>
                  <strong>Solo gestion documental</strong>
                  <small>No crea entrada ni movimiento de stock.</small>
                </span>
              </label>
              <label className="checkOption">
                <input
                  type="checkbox"
                  checked={!processOptions.documentOnly}
                  onChange={(event) => setProcessOptions((current) => ({
                    ...current,
                    documentOnly: !event.target.checked,
                    updatePrices: event.target.checked ? current.updatePrices : false,
                    updateOnlyIfUp: event.target.checked ? current.updateOnlyIfUp : false,
                    ghostLines: event.target.checked ? current.ghostLines : false,
                  }))}
                />
                <span>
                  <strong>Crear entrada de almacen</strong>
                  <small>Activa cuando no se marca solo documental.</small>
                </span>
              </label>
              <label className="checkOption">
                <input
                  type="checkbox"
                  checked={processOptions.updatePrices}
                  disabled={processOptions.documentOnly}
                  onChange={(event) => setProcessOptions((current) => ({ ...current, updatePrices: event.target.checked, updateOnlyIfUp: event.target.checked ? current.updateOnlyIfUp : false }))}
                />
                <span>
                  <strong>Actualizar precios</strong>
                  <small>Actualiza la ficha de compra si varia.</small>
                </span>
              </label>
              <label className="checkOption">
                <input
                  type="checkbox"
                  checked={processOptions.updateOnlyIfUp}
                  disabled={processOptions.documentOnly}
                  onChange={(event) => setProcessOptions((current) => ({ ...current, updatePrices: event.target.checked ? true : current.updatePrices, updateOnlyIfUp: event.target.checked }))}
                />
                <span>
                  <strong>Solo si sube el precio</strong>
                  <small>Respeta bajadas y actualiza subidas.</small>
                </span>
              </label>
              <label className="checkOption">
                <input
                  type="checkbox"
                  checked={processOptions.ghostLines}
                  disabled={processOptions.documentOnly}
                  onChange={(event) => setProcessOptions((current) => ({ ...current, ghostLines: event.target.checked }))}
                />
                <span>
                  <strong>Lineas fantasma</strong>
                  <small>Continua si falta la ficha de compra.</small>
                </span>
              </label>
            </div>
            <div className="selectionSummary">
              <strong>{selectedCount || state.pending.length}</strong>
              <span>{selectedCount ? 'seleccionados' : 'pendientes'}</span>
            </div>
            <div className="modeSummary">{state.modes[modeFromOptions(processOptions)].title}</div>
            {message && <div className="resultBox ok"><strong>Listo</strong><span>{message}</span></div>}
            {runResult && (
              <div className={`resultBox ${runHasIncidents(runResult) ? 'warning' : 'ok'}`}>
                <strong>{runHasIncidents(runResult) ? 'Integracion con incidencias' : 'Integracion finalizada'}</strong>
                <span>{runHasIncidents(runResult) ? incidentMessage(runResult) : runResult.latestLog?.summaryLine || runResult.modeTitle}</span>
              </div>
            )}
            {error && <div className="resultBox warning"><strong>Error</strong><span>{error}</span></div>}
          </section>
        </aside>

        <aside className="pendingDesk">
          <div className="searchBox">
            <Search size={17} />
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar fichero" />
          </div>
          <div className="pendingActions">
            <button
              className="iconOnlyButton"
              type="button"
              onClick={toggleAllVisible}
              title={allVisibleSelected ? 'Quitar seleccion' : 'Seleccionar todo'}
              aria-label={allVisibleSelected ? 'Quitar seleccion' : 'Seleccionar todo'}
            >
              {allVisibleSelected ? <SquareCheck size={17} /> : <Square size={17} />}
            </button>
            <span>{selectedCount || state.pending.length} en cola</span>
          </div>
          {columnsView ? (
            <PendingTable files={pending} activeFile={activeFile} selectedNames={selectedNames} onOpen={(file) => setActiveFilePath(file.path)} onToggle={toggleFile} />
          ) : (
            <div className="tileGrid">
              {pending.map((file) => (
                <PendingTile
                  key={file.path}
                  file={file}
                  active={activeFile?.path === file.path}
                  selected={selectedNames.has(file.name)}
                  onOpen={() => setActiveFilePath(file.path)}
                  onToggle={() => toggleFile(file)}
                />
              ))}
              {!pending.length && <div className="dropHint">Arrastra aqui PDFs o imagenes</div>}
            </div>
          )}
        </aside>

        <section className="viewerDesk">
          <div className="viewerTools">
            <span>{activeFile?.name || 'Sin documento'}</span>
            <input className="zoomSlider" type="range" min="55" max="160" value={zoom} onChange={(event) => setZoom(Number(event.target.value))} aria-label="Zoom" />
            {activeFile && (
              <a className="smallButton" href={activeFile.url} target="_blank" rel="noreferrer">
                <Maximize2 size={15} /> Abrir
              </a>
            )}
          </div>
          <Preview file={activeFile} zoom={zoom} />
        </section>
      </section>
      )}

      {mainTab === 'logs' && (
        <section className="tabPage">
          <LogPanel logs={state.logs} activeLog={activeLog} onSelect={(log) => loadLog(log).catch((err) => setError(String(err.message || err)))} />
        </section>
      )}

      {mainTab === 'archivo' && (
        <section className="tabPage">
          <HistoryPanel processed={state.processed} documents={state.documents} columnsView={columnsView} />
        </section>
      )}

      {notice && (
        <div className="noticeOverlay" role="alertdialog" aria-modal="true" aria-labelledby="noticeTitle">
          <div className={`noticeCard ${notice.variant === 'warning' ? 'warning' : 'info'}`}>
            <div className="noticeIcon">
              {notice.variant === 'warning' ? <AlertTriangle size={34} /> : <CheckCircle2 size={34} />}
            </div>
            <div>
              <strong id="noticeTitle">{notice.title}</strong>
              <p>{highlightedNoticeMessage(notice.message)}</p>
              {!!notice.details?.length && (
                <ul className="noticeDetails">
                  {notice.details.map((detail, index) => (
                    <li key={`${detail}-${index}`}>{highlightedNoticeMessage(detail)}</li>
                  ))}
                </ul>
              )}
            </div>
            <button type="button" onClick={() => setNotice(null)}>
              Aceptar
            </button>
          </div>
        </div>
      )}

      {dragging && (
        <div className="dropOverlay">
          <Upload size={46} />
          <strong>Soltar para copiar a Pendientes</strong>
          <span>PDFs e imagenes se incorporaran a la bandeja de integracion.</span>
        </div>
      )}
    </main>
  );
}
