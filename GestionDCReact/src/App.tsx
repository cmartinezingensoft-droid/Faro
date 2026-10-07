import {
  AlertTriangle,
  Archive,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  CircleHelp,
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
  Settings,
  Square,
  SquareCheck,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { mergeSavedRevision } from './review-state';

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
  aiConfig?: AiConfig;
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
  structuredResult?: {
    total?: number;
    procesados_ok?: number;
    documentados?: number;
    omitidos?: number;
    requiere_revision?: number;
    errores?: number;
    advertencias?: string[];
    documentos?: DocumentResult[];
  } | null;
  latestLog?: LogItem | null;
  state?: AppState;
};

type DocumentResult = {
      pdf?: string;
      pdf_meta?: {
        page_count?: number;
        blank_pages?: number[];
        processed_pages?: number[];
      };
      estado?: string;
      motivo?: string;
      error?: string;
      cabecera?: Record<string, unknown>;
      validacion?: Record<string, unknown>;
      totales?: Record<string, unknown>;
      advertencias?: string[];
      incidencias_revision?: Array<{
        codigo?: string;
        mensaje?: string;
        referencias?: string[];
        descripciones?: string[];
      }>;
      importacion?: {
        id?: string;
        estado?: string;
        version?: number;
        hash_sha256?: string;
        persistida?: boolean;
      };
      lineas_pdf_detectadas?: number;
      lineas_documento_detectadas?: number;
      lineas?: Array<Record<string, unknown>>;
      entrada?: Record<string, unknown>;
      documento_existente?: Record<string, unknown>;
      pendiente_borrado?: Record<string, unknown>;
};

type ConfirmResult = {
  ok: boolean;
  exitCode: number;
  stdout: string;
  stderr: string;
  structuredResult?: {
    ok?: boolean;
    documento?: Record<string, unknown>;
    importacion?: Record<string, unknown>;
    pendiente_borrado?: Record<string, unknown>;
    error?: {
      message?: string;
    };
  } | null;
  state?: AppState;
};

type ImportationsResult = {
  ok: boolean;
  exitCode: number;
  stdout: string;
  stderr: string;
  structuredResult?: {
    ok?: boolean;
    total?: number;
    offset?: number;
    limite?: number;
    busqueda?: string;
    documentos?: DocumentResult[];
    error?: {
      message?: string;
    };
  } | null;
};

type SaveRevisionResult = ConfirmResult & {
  structuredResult?: {
    ok?: boolean;
    importacion?: {
      id?: string;
      estado?: string;
      version?: number;
      hash_sha256?: string;
    };
    propuesta?: {
      cabecera?: Record<string, unknown>;
      lineas?: Array<Record<string, unknown>>;
      validacion?: Record<string, unknown>;
      totales?: Record<string, unknown>;
      advertencias?: string[];
      incidencias_revision?: DocumentResult['incidencias_revision'];
    };
    validacion?: Record<string, unknown>;
    totales?: Record<string, unknown>;
    error?: {
      message?: string;
    };
  } | null;
};

type RetryDocumentResult = ConfirmResult & {
  structuredResult?: {
    ok?: boolean;
    documento?: Record<string, unknown>;
    importacion?: Record<string, unknown>;
    gestion_documental?: Record<string, unknown>;
    documentos_entradas?: Record<string, unknown> | null;
    error?: {
      message?: string;
    };
  } | null;
};

type DeleteRevisionResult = SaveRevisionResult;

type CreateProvidersResult = {
  ok: boolean;
  exitCode: number;
  stdout: string;
  stderr: string;
  structuredResult?: {
    ok?: boolean;
    creados?: Array<Record<string, unknown>>;
    omitidos?: Array<Record<string, unknown>>;
    error?: {
      message?: string;
    };
  } | null;
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
  aiFallback: boolean;
};

type AiConfig = {
  enabled: boolean;
  provider: string;
  endpoint: string;
  model: string;
  apiKey?: string;
  hasApiKey?: boolean;
  temperature: number;
  maxTokens: number;
  timeoutSeconds: number;
  prompt: string;
};

type Notice = {
  title: string;
  message: string;
  details?: string[];
  variant?: 'info' | 'warning';
};

type ConfirmDialogAction = {
  value: string;
  label: string;
  style?: 'primary' | 'secondary' | 'danger';
};

type ConfirmDialogState = {
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: 'question' | 'danger';
  actions?: ConfirmDialogAction[];
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
  const structured = result.structuredResult;
  if (structured) {
    return !result.ok
      || Number(structured.errores || 0) > 0
      || Number(structured.omitidos || 0) > 0
      || Number(structured.requiere_revision || 0) > 0
      || Boolean(structured.documentos?.some((item) => item.pendiente_borrado?.borrado === false))
      || Boolean(structured.documentos?.some((item) => item.estado === 'error' || item.estado === 'omitido' || item.estado === 'requiere_revision'));
  }
  return !result.ok || logHasIncidents(result.latestLog);
}

function runHasConfirmableProposals(result: RunResult) {
  return Boolean(result.structuredResult?.documentos?.some((item) => (
    (item.estado === 'propuesta' && item.validacion?.can_create_entry === true)
    || (item.importacion?.id && item.validacion?.can_create_entry === true && item.estado !== 'procesado' && item.estado !== 'documentado')
  )));
}

function isMissingArticleIncidentText(value?: string) {
  return /unresolved_article|articulo no encontrado|artículos? no encontrados?|referencia de proveedor no encontrada/i.test(String(value || ''));
}

function runHasMissingArticleIncident(result: RunResult) {
  const structured = result.structuredResult;
  if (structured?.advertencias?.some((warning) => isMissingArticleIncidentText(warning))) return true;
  if (structured?.documentos?.some((item) => (
    Number(item.validacion?.unresolved_lines || 0) > 0
    || item.incidencias_revision?.some((incident) => isMissingArticleIncidentText(incident.codigo) || isMissingArticleIncidentText(incident.mensaje))
    || isMissingArticleIncidentText(item.motivo)
    || isMissingArticleIncidentText(item.error)
  ))) return true;
  const content = result.latestLog?.content || '';
  return content.split(/\r?\n/).map(logMessage).some((line) => /Articulo no encontrado/i.test(line) && !isGhostArticleLine(line));
}

function existingEntryText(existing?: Record<string, unknown>) {
  if (!existing) return '';
  const centro = existing.CBM_CENTRO ?? existing.centro;
  const ejercicio = existing.CBM_EJERCI ?? existing.ejercicio;
  const serie = existing.CBM_SERIE ?? existing.serie;
  const numero = existing.CBM_NUMDOC ?? existing.numero;
  const entry = [ejercicio, serie, numero].filter((value) => String(value ?? '').trim()).join('-');
  return [centro !== undefined && centro !== null && String(centro).trim() ? `centro ${centro}` : '', entry ? `entrada ${entry}` : '']
    .filter(Boolean)
    .join(', ');
}

function duplicateDocumentIncident(result: RunResult) {
  return result.structuredResult?.documentos?.find((item) => (
    item.documento_existente
    || /documento ya dado de alta|ya dado de alta/i.test(`${item.motivo || ''} ${item.error || ''}`)
  ));
}

function hasProviderIncidentText(value?: string) {
  return /provider_unresolved|proveedor (?:no encontrado|inexistente)|proveedor no existe|cif=.*proveedor/i.test(String(value || ''));
}

function runHasProviderIncident(result: RunResult) {
  const structured = result.structuredResult;
  if (structured?.documentos?.some((item) => (
    (item.validacion?.provider_resolved === false && item.cabecera?.solo_gestion_documental !== true)
    || hasProviderIncidentText(item.motivo)
    || hasProviderIncidentText(item.error)
    || item.incidencias_revision?.some((incident) => hasProviderIncidentText(incident.codigo) || hasProviderIncidentText(incident.mensaje))
  ))) return true;
  const content = result.latestLog?.content || '';
  return content.split(/\r?\n/).map(logMessage).some((line) => hasProviderIncidentText(line));
}

function missingProviderDocuments(result: RunResult) {
  const seen = new Set<string>();
  return (result.structuredResult?.documentos || []).filter((item) => {
    if (item.cabecera?.solo_gestion_documental === true || item.validacion?.provider_resolved !== false) return false;
    const header = item.cabecera || {};
    const key = String(header.cif || header.nombre_proveedor || item.pdf || '').trim().toUpperCase();
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function providerCreationSummary(documents: DocumentResult[]) {
  return documents.map((item) => {
    const header = item.cabecera || {};
    const name = String(header.nombre_proveedor || 'Proveedor sin nombre').trim();
    const cif = String(header.cif || '').trim();
    return cif ? `${name} (${cif})` : name;
  }).join(', ');
}

function normalizeIncidentText(value: unknown) {
  return textValue(value)
    .replace(/\uFFFD/g, 'á')
    .replace(/\bestá\b/gi, (match) => (match[0] === 'E' ? 'Está' : 'está'))
    .replace(/\s+/g, ' ')
    .trim();
}

function isFileLockedIncidentText(value?: string) {
  return /WinError 32|no tiene acceso al archivo porque .*siendo utilizado por otro proceso|being used by another process/i.test(normalizeIncidentText(value));
}

function runHasFileLockedIncident(result: RunResult) {
  const structured = result.structuredResult;
  if (structured?.documentos?.some((item) => isFileLockedIncidentText(item.error) || isFileLockedIncidentText(item.motivo))) return true;
  const content = result.latestLog?.content || '';
  return content.split(/\r?\n/).map(logMessage).some((line) => isFileLockedIncidentText(line));
}

function isNoDetailLinesIncidentText(value?: string) {
  return /no se han detectado lineas de detalle suficientes|no se detectaron lineas de entrada|no_lines_detected/i.test(normalizeIncidentText(value));
}

function runHasNoDetailLinesIncident(result: RunResult) {
  const structured = result.structuredResult;
  if (structured?.documentos?.some((item) => (
    item.validacion?.no_lines_detected === true
    || isNoDetailLinesIncidentText(item.motivo)
    || isNoDetailLinesIncidentText(item.error)
    || item.incidencias_revision?.some((incident) => isNoDetailLinesIncidentText(incident.codigo) || isNoDetailLinesIncidentText(incident.mensaje))
  ))) return true;
  const content = result.latestLog?.content || '';
  return content.split(/\r?\n/).map(logMessage).some((line) => isNoDetailLinesIncidentText(line));
}

function runHasTotalMismatchIncident(result: RunResult) {
  return Boolean(result.structuredResult?.documentos?.some((item) => (
    item.validacion?.total_reconciled === false
    || item.advertencias?.some((warning) => /total_mismatch|descuadre/i.test(String(warning || '')))
    || item.incidencias_revision?.some((incident) => /total_mismatch|total calculado no cuadra/i.test(`${incident.codigo || ''} ${incident.mensaje || ''}`))
  )));
}

function entryText(entry?: Record<string, unknown>) {
  if (!entry) return '';
  const centro = entry.centro ?? entry.CBM_CENTRO;
  const ejercicio = entry.ejercicio ?? entry.CBM_EJERCI;
  const serie = entry.serie ?? entry.CBM_SERIE;
  const numero = entry.numero ?? entry.CBM_NUMDOC;
  const doc = [ejercicio, serie, numero].filter((value) => String(value ?? '').trim()).join('-');
  return [centro !== undefined && centro !== null && String(centro).trim() ? `centro ${centro}` : '', doc ? `entrada ${doc}` : '']
    .filter(Boolean)
    .join(', ');
}

function pendingDeleteIncident(result: RunResult) {
  return result.structuredResult?.documentos?.find((item) => (
    (item.estado === 'procesado' || item.estado === 'documentado')
    && item.pendiente_borrado?.borrado === false
  ));
}

function incidentMessage(result: RunResult) {
  const pendingDelete = pendingDeleteIncident(result);
  if (pendingDelete) {
    const entry = entryText(pendingDelete.entrada);
    const prefix = entry ? `Entrada generada correctamente: ${entry}.` : 'Documento integrado correctamente.';
    return `${prefix} No se ha podido borrar el PDF pendiente porque está abierto o bloqueado por otro proceso.`;
  }
  const duplicate = duplicateDocumentIncident(result);
  if (duplicate) {
    const existing = existingEntryText(duplicate.documento_existente);
    return existing
      ? `Documento ya dado de alta. Entrada existente: ${existing}.`
      : 'Documento ya dado de alta.';
  }
  if (runHasTotalMismatchIncident(result)) {
    return 'No se ha podido procesar porque el total calculado no cuadra con el documento.';
  }
  if (runHasProviderIncident(result)) {
    return 'No se ha podido procesar porque el proveedor no existe.';
  }
  if (runHasMissingArticleIncident(result)) {
    return 'No se ha podido procesar porque no se ha encontrado el articulo.';
  }
  if (runHasFileLockedIncident(result)) {
    return 'No se ha podido procesar porque el PDF está abierto o bloqueado por otro proceso.';
  }
  if (runHasNoDetailLinesIncident(result)) {
    return 'No se ha podido procesar porque no se han detectado líneas de detalle.';
  }
  const structured = result.structuredResult;
  const incident = structured?.documentos?.find((item) => item.estado === 'error' || item.estado === 'requiere_revision' || item.estado === 'omitido');
  if (incident) {
    const reviewMessage = incident.incidencias_revision?.find((item) => item.mensaje)?.mensaje;
    return normalizeIncidentText(incident.error || reviewMessage || incident.motivo || `Documento ${incident.estado || 'con incidencias'}`);
  }
  const content = result.latestLog?.content || '';
  const messages = content.split(/\r?\n/).map(logMessage).filter(Boolean);
  const cause = messages.find((line) => !isGhostArticleLine(line) && /\bERROR\b|Proveedor no encontrado|Articulo no encontrado|Documento omitido|ya dado de alta|No se pudo/i.test(line));
  return normalizeIncidentText(cause || result.latestLog?.cause || result.latestLog?.summaryLine || result.stderr || 'La integracion ha finalizado con incidencias.');
}

function highlightedNoticeMessage(message: string) {
  const normalizedMessage = normalizeIncidentText(message);
  const parts = normalizedMessage.split(/(Entrada generada correctamente:[^.]*(?:\.)?|Documento integrado correctamente|Documento ya dado de alta|Entrada existente:[^.]*(?:\.)?|Proveedor no encontrado|proveedor no existe|proveedor inexistente|Articulo no encontrado|Artículo no encontrado|articulo no encontrado|PDF está abierto|bloqueado por otro proceso|no se han detectado líneas de detalle|No se ha podido procesar|\berror\b|No se pudo)/i);
  return parts.map((part, index) => (
    /Entrada generada correctamente|Documento integrado correctamente|Documento ya dado de alta|Entrada existente|Proveedor no encontrado|proveedor no existe|proveedor inexistente|Articulo no encontrado|Artículo no encontrado|articulo no encontrado|PDF está abierto|bloqueado por otro proceso|no se han detectado líneas de detalle|No se ha podido procesar|\berror\b|No se pudo/i.test(part)
      ? <span className="noticeErrorText" key={`${part}-${index}`}>{part}</span>
      : part
  ));
}

function highlightedNoticeDetail(detail: string) {
  const normalizedDetail = normalizeIncidentText(detail);
  const parts = normalizedDetail.split(/(\bentrada\s+\d{4}-[A-Z0-9]+-\d+\b|Entrada generada:[^.]*(?:\.)?)/i);
  return parts.map((part, index) => (
    /^(?:\bentrada\s+\d{4}-[A-Z0-9]+-\d+\b|Entrada generada:)/i.test(part)
      ? <span className="noticeEntryText" key={`${part}-${index}`}>{part}</span>
      : highlightedNoticeMessage(part)
  ));
}

function integrationReport(result: RunResult) {
  const pendingDelete = pendingDeleteIncident(result);
  if (pendingDelete) {
    const entry = entryText(pendingDelete.entrada);
    const path = String(pendingDelete.pendiente_borrado?.ruta || '').trim();
    return [
      ...(entry ? [`Entrada generada: ${entry}`] : []),
      ...(path ? [`PDF pendiente: ${path}`] : []),
    ];
  }
  const duplicate = duplicateDocumentIncident(result);
  if (duplicate) {
    const existing = existingEntryText(duplicate.documento_existente);
    return existing ? [`Entrada existente: ${existing}`] : [];
  }
  if (runHasMissingArticleIncident(result)) {
    return [];
  }
  if (runHasProviderIncident(result)) {
    return [];
  }
  if (runHasFileLockedIncident(result)) {
    return [];
  }
  if (runHasNoDetailLinesIncident(result)) {
    return [];
  }
  const structured = result.structuredResult;
  if (structured) {
    const details: string[] = [
      `Documentos detectados: ${Number(structured.total || 0)}`,
      `Procesados correctamente: ${Number(structured.procesados_ok || 0)}`,
      `Propuestas listas para confirmar: ${structured.documentos?.filter((item) => item.estado === 'propuesta').length || 0}`,
      `Solo documentados: ${Number(structured.documentados || 0)}`,
      `Pendientes de revision: ${Number(structured.requiere_revision || 0)}`,
      `Omitidos: ${Number(structured.omitidos || 0)}`,
      `Errores: ${Number(structured.errores || 0)}`,
    ];
    const confirmableCount = structured.documentos?.filter((item) => item.estado === 'propuesta').length || 0;
    if (confirmableCount > 0) {
      details.push('Entrada de almacen no creada: falta pulsar Confirmar propuesta en Revision.');
    }
    structured.documentos?.forEach((item) => {
      const name = item.pdf ? item.pdf.split(/[\\/]/).pop() : 'documento';
      if (item.estado === 'procesado' && item.entrada) {
        const entry = item.entrada as Record<string, unknown>;
        details.push(`${name}: entrada ${entry.ejercicio || ''}-${entry.serie || ''}-${entry.numero || ''}`);
      }
      if (item.estado === 'documentado') details.push(`${name}: archivado sin entrada`);
      if (item.estado === 'propuesta') {
        const reviewId = item.importacion?.id ? ` propuesta ${item.importacion.id}` : '';
        details.push(`${name}: entrada no creada; pendiente de confirmar propuesta IA${reviewId}`);
      }
      if (item.estado === 'requiere_revision') {
        const reviewId = item.importacion?.id ? ` propuesta ${item.importacion.id}` : '';
        details.push(`${name}: requiere revision${reviewId} (${item.motivo || 'validacion pendiente'})`);
        item.incidencias_revision?.forEach((incident) => {
          if (incident.mensaje) details.push(`${name}: ${incident.mensaje}`);
        });
      }
      if (item.estado === 'omitido') details.push(`${name}: omitido (${item.motivo || 'duplicado o politica de lote'})`);
      if (item.estado === 'error') details.push(`${name}: error (${item.error || 'sin detalle'})`);
      if (item.validacion?.total_reconciled === false && item.totales) {
        details.push(`${name}: descuadre total documento ${item.totales.source_gross ?? '?'} / calculado ${item.totales.computed_gross ?? '?'}`);
      }
    });
    return details;
  }
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

let sessionToken: Promise<string> | null = null;
async function localSessionToken(): Promise<string> {
  if (!sessionToken) sessionToken = fetch('/api/session')
    .then(async (response) => {
      if (!response.ok) throw new Error('No se pudo iniciar la sesion local');
      return String((await response.json()).token || '');
    }).catch((error) => { sessionToken = null; throw error; });
  return sessionToken;
}
async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.method && !['GET', 'HEAD'].includes(init.method.toUpperCase())) {
    headers.set('x-gdc-token', await localSessionToken());
  }
  const response = await fetch(url, { ...init, headers });
  if (response.status === 403) sessionToken = null;
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

function Preview({ file, zoom, page = 1 }: { file?: FileItem; zoom: number; page?: number }) {
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
    const params = new URLSearchParams({ path: file.path, page: String(page) });
    return (
      <div className="imagePreview pdfPreview">
        <img src={`/api/preview?${params.toString()}`} alt={file.name} style={{ width: `${zoom}%` }} />
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

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? { ...(value as Record<string, unknown>) } : {};
}

function textValue(value: unknown) {
  return value === undefined || value === null ? '' : String(value);
}

function emptyReviewLine(): Record<string, unknown> {
  return {
    referencia_proveedor: '',
    articulo: '',
    descripcion: '',
    cantidad: '1',
    precio: '',
    descuento1: '',
    iva: '21',
    importe_origen: '',
    seleccion_articulo: 'manual',
  };
}

function cleanIssueText(value: unknown) {
  const text = normalizeIncidentText(value)
    .replace(/\s+/g, ' ')
    .replace(/^Command failed:\s*/i, '')
    .trim();
  if (!text) return '';
  if (isFileLockedIncidentText(text)) {
    return 'El PDF está abierto o bloqueado por otro proceso.';
  }
  if (/^Traceback/i.test(text)) {
    return 'Error tecnico al guardar la propuesta; revisa el log de integracion para ver la ultima linea del fallo.';
  }
  if (/invalid literal for int\(\)/i.test(text)) {
    return 'La IA devolvio un campo numerico con texto; refresca y vuelve a lanzar la revision con la cabecera normalizada.';
  }
  if (/decimal\.ConversionSyntax|ConversionSyntax/i.test(text)) {
    return 'Hay un campo numerico con formato no valido; revisa cantidades, precios, descuentos, IVA e importes.';
  }
  if (text.includes('persist_ai_importation.py') || text.includes('"cabecera"') || text.includes('"lineas"')) {
    return 'La propuesta de IA no se pudo guardar en GDC_IMPORTACION; revisa el log de integracion para el detalle tecnico.';
  }
  return text.length > 260 ? `${text.slice(0, 257)}...` : text;
}

function defaultAiConfig(): AiConfig {
  return {
    enabled: false,
    provider: 'openai-compatible',
    endpoint: 'https://api.openai.com/v1/chat/completions',
    model: 'gpt-4o-mini',
    apiKey: '',
    hasApiKey: false,
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
}

function normalizeAiConfig(value?: Partial<AiConfig> | null): AiConfig {
  const base = defaultAiConfig();
  return {
    ...base,
    ...(value || {}),
    temperature: Number(value?.temperature ?? base.temperature),
    maxTokens: Number(value?.maxTokens ?? base.maxTokens),
    timeoutSeconds: Number(value?.timeoutSeconds ?? base.timeoutSeconds),
    apiKey: value?.apiKey || '',
  };
}

function AiConfigDialog({
  initialConfig,
  saving,
  error,
  onCancel,
  onSave,
}: {
  initialConfig?: AiConfig;
  saving: boolean;
  error: string;
  onCancel: () => void;
  onSave: (config: AiConfig) => void;
}) {
  const [draft, setDraft] = useState<AiConfig>(() => normalizeAiConfig(initialConfig));

  function setField<K extends keyof AiConfig>(field: K, value: AiConfig[K]) {
    setDraft((current) => ({ ...current, [field]: value }));
  }

  return (
    <div className="noticeOverlay aiConfigOverlay" role="dialog" aria-modal="true" aria-labelledby="aiConfigTitle">
      <section className="aiConfigCard">
        <header>
          <div>
            <span className="eyebrow">IA</span>
            <h2 id="aiConfigTitle">Configurar llamada</h2>
          </div>
          <button className="iconOnlyButton" type="button" onClick={onCancel} title="Cerrar">
            <X size={17} />
          </button>
        </header>
        <div className="aiConfigBody">
          <label className="checkOption aiEnableOption">
            <input type="checkbox" checked={draft.enabled} onChange={(event) => setField('enabled', event.target.checked)} />
            <span>
              <strong>Activar fallback con IA</strong>
              <small>Se usara solo si el proceso directo no deja el PDF integrado.</small>
            </span>
          </label>
          <div className="fieldGrid aiConfigGrid">
            <label>
              <span>Proveedor</span>
              <input value={draft.provider} onChange={(event) => setField('provider', event.target.value)} />
            </label>
            <label>
              <span>Modelo</span>
              <input value={draft.model} onChange={(event) => setField('model', event.target.value)} />
            </label>
            <label className="wideField">
              <span>Endpoint</span>
              <input value={draft.endpoint} onChange={(event) => setField('endpoint', event.target.value)} />
            </label>
            <label className="wideField">
              <span>API key</span>
              <input
                type="password"
                value={draft.apiKey || ''}
                placeholder={draft.hasApiKey ? 'Clave guardada; escribe otra para cambiarla' : 'Clave del proveedor'}
                onChange={(event) => setField('apiKey', event.target.value)}
              />
            </label>
            <label>
              <span>Temperatura</span>
              <input type="number" min="0" max="2" step="0.1" value={draft.temperature} onChange={(event) => setField('temperature', Number(event.target.value))} />
            </label>
            <label>
              <span>Max tokens</span>
              <input type="number" min="500" step="100" value={draft.maxTokens} onChange={(event) => setField('maxTokens', Number(event.target.value))} />
            </label>
            <label>
              <span>Timeout seg.</span>
              <input type="number" min="10" step="5" value={draft.timeoutSeconds} onChange={(event) => setField('timeoutSeconds', Number(event.target.value))} />
            </label>
          </div>
          <label className="promptField">
            <span>Prompt</span>
            <textarea value={draft.prompt} onChange={(event) => setField('prompt', event.target.value)} />
          </label>
          {error && <div className="resultBox warning"><strong>No se pudo guardar</strong><span>{error}</span></div>}
        </div>
        <footer>
          <button type="button" onClick={onCancel} disabled={saving}>Cancelar</button>
          <button type="button" onClick={() => onSave(draft)} disabled={saving}>
            {saving ? 'Guardando...' : 'Guardar'}
          </button>
        </footer>
      </section>
    </div>
  );
}

function ConfirmDialog({
  title,
  message,
  confirmText = 'Aceptar',
  cancelText = 'Cancelar',
  variant = 'question',
  actions,
  onConfirm,
  onCancel,
  onAction,
}: {
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: 'question' | 'danger';
  actions?: ConfirmDialogAction[];
  onConfirm: () => void;
  onCancel: () => void;
  onAction?: (value: string) => void;
}) {
  const dialogActions = actions?.length ? actions : null;
  return (
    <div className="noticeOverlay" role="alertdialog" aria-modal="true" aria-labelledby="confirmDialogTitle">
      <div className={`noticeCard aiConfirmCard ${variant === 'danger' ? 'warning' : 'question'}`}>
        <div className="noticeIcon">
          <CircleHelp size={34} />
        </div>
        <div>
          <strong id="confirmDialogTitle">{title}</strong>
          <p>{message}</p>
        </div>
        <div className="confirmActions">
          {dialogActions
            ? dialogActions.map((action) => (
              <button
                key={action.value}
                type="button"
                className={`${action.style || 'secondary'}Action`}
                onClick={() => onAction?.(action.value)}
              >
                {action.label}
              </button>
            ))
            : (
              <>
                <button type="button" className="secondaryAction" onClick={onCancel}>
                  {cancelText}
                </button>
                <button type="button" className="primaryAction" onClick={onConfirm}>
                  {confirmText}
                </button>
              </>
            )}
        </div>
      </div>
    </div>
  );
}

function validationIssues(item?: DocumentResult) {
  const issues: string[] = [];
  const addIssue = (message: string) => {
    const clean = cleanIssueText(message).replace(/\.$/, '');
    if (clean && !issues.includes(clean)) issues.push(clean);
  };
  if (!item) return issues;
  const validation = item.validacion || {};
  const unresolved = Number(validation.unresolved_lines || 0);
  const ghostLinesAllowed = validation.ghost_lines_allowed === true
    || String(item.cabecera?.politica_articulo_no_encontrado || '').toLowerCase() === 'fantasma';
  if (validation.provider_resolved === false && item.cabecera?.solo_gestion_documental !== true) {
    addIssue('Selecciona un proveedor valido antes de confirmar la entrada');
  }
  const hasMissingArticleSupplierIssue = (
    unresolved > 0
    || item.incidencias_revision?.some((incident) => isMissingArticleIncidentText(incident.codigo) || isMissingArticleIncidentText(incident.mensaje))
    || isMissingArticleIncidentText(item.motivo)
    || isMissingArticleIncidentText(item.error)
  );
  if (validation.can_create_entry === false && hasMissingArticleSupplierIssue && !ghostLinesAllowed) {
    addIssue('No se ha podido integrar porque no se ha encontrado el articulo-proveedor.');
  }
  if (validation.can_create_entry === false && (
    validation.no_lines_detected === true
    || item.incidencias_revision?.some((incident) => isNoDetailLinesIncidentText(incident.codigo) || isNoDetailLinesIncidentText(incident.mensaje))
    || isNoDetailLinesIncidentText(item.motivo)
    || isNoDetailLinesIncidentText(item.error)
  )) {
    addIssue('No se ha podido integrar porque no se han detectado líneas de detalle.');
  }
  const importation = item.importacion || {};
  const persisted = importation.persistida !== false && Boolean(importation.id);
  if (!persisted) {
    const reason = cleanIssueText((importation as Record<string, unknown>).motivo);
    addIssue(`Propuesta no guardada${reason ? ` (${reason})` : ''}`);
  }
  if (!item.lineas?.length && item.cabecera?.solo_gestion_documental !== true) {
    addIssue('No se han detectado lineas de detalle');
  }
  if (unresolved > 0) {
    const refs = (item.lineas || [])
      .filter((line) => !String(line.articulo || '').trim())
      .map((line) => String(line.referencia_proveedor || line.descripcion || '').trim())
      .filter(Boolean);
    const detail = refs.length ? `: ${refs.join(', ')}` : '';
    addIssue(ghostLinesAllowed
      ? `Se grabaran ${unresolved} linea(s) fantasma${detail}`
      : `Faltan ${unresolved} articulo(s)${detail}`);
  }
  if (validation.total_reconciled === false) addIssue('El total calculado no cuadra con el documento');
  item.incidencias_revision?.forEach((incident) => {
    const message = cleanIssueText(incident.mensaje);
    if (/propuesta generada por ia|revisa la propuesta de ia|pendiente de revision/i.test(message)) return;
    if (message) addIssue(message);
  });
  const hasAiWarning = item.advertencias?.some((warning) => /propuesta generada por ia|revisa proveedor|precios|impuestos/i.test(String(warning || '')));
  if (hasAiWarning) addIssue('Revisa proveedor, referencias, cantidades, precios e impuestos antes de confirmar');
  item.advertencias?.forEach((warning) => {
    const message = cleanIssueText(warning);
    if (/propuesta generada por ia|revisa proveedor|esta propuesta no crea entrada/i.test(message)) return;
    if (message) addIssue(message);
  });
  if (/propuesta generada por ia|ia lista para confirmar|pendiente de revision/i.test(String(item.motivo || ''))) {
    addIssue('Pendiente de confirmar; aun no se ha creado la entrada');
  } else if (item.motivo && !issues.some((issue) => issue.includes(String(item.motivo)))) {
    addIssue(cleanIssueText(item.motivo));
  }
  if (validation.can_create_entry === false && !issues.length) {
    addIssue('La validacion de la propuesta no permite crear la entrada');
  }
  return issues;
}

function unresolvedReviewLineCount(item?: DocumentResult, lines?: Array<Record<string, unknown>>) {
  const draftLines = lines || item?.lineas || [];
  const draftUnresolved = draftLines.filter((line) => !String(line.articulo || '').trim()).length;
  return Math.max(Number(item?.validacion?.unresolved_lines || 0), draftUnresolved);
}

function reviewGhostPolicyAllowed(item?: DocumentResult, header?: Record<string, unknown>) {
  const validation = item?.validacion || {};
  const policy = String(
    header?.politica_articulo_no_encontrado
    || item?.cabecera?.politica_articulo_no_encontrado
    || '',
  ).toLowerCase();
  return validation.ghost_lines_allowed === true || policy === 'fantasma';
}

function canConfirmWithGhostPolicy(item?: DocumentResult, lines?: Array<Record<string, unknown>>, header?: Record<string, unknown>) {
  if (!item?.importacion?.id || item.validacion?.can_create_entry !== false) return false;
  if (!reviewGhostPolicyAllowed(item, header)) return false;
  if (unresolvedReviewLineCount(item, lines) <= 0) return false;
  const validation = item.validacion || {};
  return !validation.line_limit_reached
    && validation.pages_complete !== false
    && validation.provider_resolved !== false
    && validation.total_reconciled !== false
    && validation.no_lines_detected !== true
    && validation.evidence_low_confidence !== true;
}

function canConfirmWithGhostPrompt(item?: DocumentResult, lines?: Array<Record<string, unknown>>, header?: Record<string, unknown>) {
  if (reviewGhostPolicyAllowed(item, header)) return false;
  return canConfirmWithGhostPolicy(item, lines, {
    ...(header || {}),
    politica_articulo_no_encontrado: 'fantasma',
  });
}

function normalizeReviewDraftForCompare(value: Record<string, unknown>) {
  const result: Record<string, unknown> = {};
  Object.entries(value || {}).forEach(([key, fieldValue]) => {
    if (fieldValue === undefined || fieldValue === null || fieldValue === '') return;
    result[key] = fieldValue;
  });
  return result;
}

function normalizeReviewLineForCompare(line: Record<string, unknown>) {
  const result = normalizeReviewDraftForCompare(line);
  const article = String(result.articulo || '').trim();
  const selection = String(result.article_selection || result.seleccion_articulo || '').trim().toLowerCase();
  if (!article && (!selection || selection === 'manual' || selection === 'auto')) {
    delete result.article_selection;
    delete result.seleccion_articulo;
  }
  return result;
}

function reviewDocumentKey(item: DocumentResult) {
  if (item.importacion?.id) return `id:${item.importacion.id}`;
  const hash = String(item.importacion?.hash_sha256 || '').trim().toLowerCase();
  if (hash) return `hash:${hash}`;
  const pdf = String(item.pdf || '').trim().toLowerCase();
  const albaran = String(item.cabecera?.albaran || '').trim().toLowerCase();
  const factura = String(item.cabecera?.factura || '').trim().toLowerCase();
  return `doc:${pdf}|${albaran}|${factura}`;
}

function dedupeReviewDocuments(items: DocumentResult[]) {
  const result: DocumentResult[] = [];
  const seen = new Set<string>();
  for (const item of items) {
    const key = reviewDocumentKey(item);
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(item);
  }
  return result;
}

function ReviewPanel({
  runResult,
  state,
  onConfirmed,
  onAskConfirm,
}: {
  runResult: RunResult | null;
  state: AppState;
  onConfirmed: (result: ConfirmResult) => void;
  onAskConfirm: (dialog: ConfirmDialogState) => Promise<boolean>;
}) {
  const documents = runResult?.structuredResult?.documentos || [];
  const [storedDocs, setStoredDocs] = useState<DocumentResult[]>([]);
  const [loadingStored, setLoadingStored] = useState(false);
  const [storedError, setStoredError] = useState('');
  const [reviewSearch, setReviewSearch] = useState('');
  const [showConfirmed, setShowConfirmed] = useState(false);
  const [reviewOffset, setReviewOffset] = useState(0);
  const [storedTotal, setStoredTotal] = useState(0);
  const [deletedImportationIds, setDeletedImportationIds] = useState<Set<string>>(new Set());
  const reviewLimit = 25;
  const reviewableDocuments = documents.filter((item) => (
    (showConfirmed === ['CONFIRMADA', 'DOCUMENTADA'].includes(String(item.importacion?.estado || item.estado || '').toUpperCase())) && (
    item.estado === 'simulado'
    || item.estado === 'requiere_revision'
    || item.estado === 'propuesta'
    || (item.importacion?.id && item.estado !== 'procesado' && item.estado !== 'documentado')
  )));
  const reviewDocs = dedupeReviewDocuments([
    ...storedDocs,
    ...reviewableDocuments,
  ].filter((item) => !item.importacion?.id || !deletedImportationIds.has(String(item.importacion.id))));
  const [activeIndex, setActiveIndex] = useState(0);
  const active = reviewDocs[Math.min(activeIndex, Math.max(0, reviewDocs.length - 1))];
  const [headerDraft, setHeaderDraft] = useState<Record<string, unknown>>({});
  const [linesDraft, setLinesDraft] = useState<Array<Record<string, unknown>>>([]);
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deletingRevision, setDeletingRevision] = useState(false);
  const [retryingDocument, setRetryingDocument] = useState(false);
  const [error, setError] = useState('');
  const [savedMessage, setSavedMessage] = useState('');
  const [reviewPage, setReviewPage] = useState(1);
  const activeIssues = validationIssues(active);
  const ghostPromptAvailable = canConfirmWithGhostPrompt(active, linesDraft, headerDraft);
  const ghostPolicyConfirmable = canConfirmWithGhostPolicy(active, linesDraft, headerDraft);
  const isDocumentOnly = headerDraft.solo_gestion_documental === true;
  const hasConfirmableLines = linesDraft.length > 0 || isDocumentOnly;
  const draftDirty = JSON.stringify(normalizeReviewDraftForCompare(headerDraft)) !== JSON.stringify(normalizeReviewDraftForCompare(active?.cabecera || {}))
    || JSON.stringify(linesDraft.map((line) => normalizeReviewLineForCompare(line))) !== JSON.stringify((active?.lineas || []).map((line) => normalizeReviewLineForCompare(line)));
  const canConfirmEntry = active?.validacion?.can_create_entry === true || ghostPromptAvailable || ghostPolicyConfirmable;
  const confirmBlocked = !active?.importacion?.id || !hasConfirmableLines || draftDirty || showConfirmed
    || (isDocumentOnly ? active?.validacion?.can_archive_document !== true : !canConfirmEntry);
  const documentRetryEnabled = Boolean(active?.importacion?.id && String(active.importacion.estado || active.estado || '').toUpperCase() === 'CONFIRMADA');
  const deleteRevisionEnabled = Boolean(
    active?.importacion?.id
    && !['CONFIRMADA', 'DOCUMENTADA'].includes(String(active.importacion.estado || active.estado || '').toUpperCase())
  );
  const pageTotal = Math.max(1, Number(active?.pdf_meta?.page_count || 1));
  const sourceFile = active?.pdf
    ? {
        name: active.pdf.split(/[\\/]/).pop() || active.pdf,
        path: active.pdf,
        relative: active.pdf,
        extension: active.pdf.split('.').pop() ? `.${active.pdf.split('.').pop()}` : '.pdf',
        kind: /\.pdf$/i.test(active.pdf) ? 'pdf' as FileKind : 'image' as FileKind,
        size: 0,
        modifiedAt: new Date().toISOString(),
        url: `/api/file?path=${encodeURIComponent(active.pdf)}`,
      }
    : undefined;

  useEffect(() => {
    setActiveIndex(0);
  }, [runResult]);

  useEffect(() => {
    const controller = new AbortController();
    setLoadingStored(true);
    const params = new URLSearchParams({
      limit: String(reviewLimit),
      offset: String(reviewOffset),
      search: reviewSearch,
      estados: showConfirmed ? 'CONFIRMADA,DOCUMENTADA' : 'PROPUESTA,REVISADA',
    });
    requestJson<ImportationsResult>(`/api/importations?${params.toString()}`, { signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return;
        setStoredDocs(result.structuredResult?.documentos || []);
        setStoredTotal(Number(result.structuredResult?.total || 0));
        setStoredError('');
      })
      .catch((err: any) => { if (!controller.signal.aborted) setStoredError(String(err.message || err)); })
      .finally(() => { if (!controller.signal.aborted) setLoadingStored(false); });
    return () => controller.abort();
  }, [state, reviewOffset, reviewSearch, showConfirmed]);

  useEffect(() => { setActiveIndex(0); }, [reviewOffset, reviewSearch, showConfirmed]);

  const activeDraftKey = [
    active?.pdf || '',
    active?.importacion?.id || '',
    active?.importacion?.version || '',
    active?.lineas?.length || 0,
  ].join('|');

  useEffect(() => {
    setHeaderDraft(asRecord(active?.cabecera || {}));
    setLinesDraft((active?.lineas || []).map((line) => asRecord(line)));
    setReviewPage(1);
    setError('');
    setSavedMessage('');
  }, [activeDraftKey]);

  function setHeaderField(field: string, value: string) {
    setHeaderDraft((current) => ({ ...current, [field]: value }));
  }

  function setLineField(index: number, field: string, value: string) {
    setLinesDraft((current) => current.map((line, lineIndex) => (
      lineIndex === index ? { ...line, [field]: value, ...(field === 'articulo' ? { seleccion_articulo: 'manual', article_selection: 'manual' } : {}) } : line
    )));
  }

  async function confirmActive() {
    if (!active?.importacion?.id) return;
    let confirmHeaderDraft = headerDraft;
    if (ghostPromptAvailable) {
      const unresolved = unresolvedReviewLineCount(active, linesDraft);
      const confirmed = await onAskConfirm({
        title: 'Grabar lineas fantasma',
        message: `No se han encontrado ${unresolved} articulo(s). ¿Desea grabarlos como lineas fantasma?`,
        confirmText: 'Grabar fantasma',
      });
      if (!confirmed) return;
      confirmHeaderDraft = {
        ...headerDraft,
        politica_articulo_no_encontrado: 'fantasma',
      };
    }
    setConfirming(true);
    setError('');
    try {
      const result = await requestJson<ConfirmResult>('/api/confirm-importation', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          propuestaId: active.importacion.id,
          version: active.importacion.version,
          hashSha256: active.importacion.hash_sha256,
          cabecera: confirmHeaderDraft,
          lineas: linesDraft,
        }),
      });
      if (result.ok && active.importacion) {
        const confirmed: DocumentResult = { ...active,
          cabecera: { ...confirmHeaderDraft }, lineas: linesDraft.map((line) => ({ ...line })),
          importacion: { ...active.importacion, estado: String(result.structuredResult?.importacion?.estado || 'CONFIRMADA') },
          estado: 'confirmada',
        };
        setStoredDocs((current) => [confirmed, ...current.filter((item) => item.importacion?.id !== confirmed.importacion?.id)]);
        setShowConfirmed(true);
        setReviewOffset(0);
        setActiveIndex(0);
      }
      onConfirmed(result);
    } catch (err: any) {
      const payload = err.payload as ConfirmResult | undefined;
      setError(cleanIssueText(payload?.structuredResult?.error?.message || String(err.message || err)));
    } finally {
      setConfirming(false);
    }
  }

  async function retryDocumentActive() {
    if (!active?.importacion?.id) return;
    setRetryingDocument(true);
    setError('');
    setSavedMessage('');
    try {
      const result = await requestJson<RetryDocumentResult>('/api/retry-importation-document', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          propuestaId: active.importacion.id,
          copiarDocumentosEntradas: true,
        }),
      });
      const doc = result.structuredResult?.gestion_documental as Record<string, unknown> | undefined;
      setSavedMessage(doc?.existente ? 'Documento ya estaba archivado; no se ha duplicado.' : 'Archivo documental reintentado correctamente.');
    } catch (err: any) {
      const payload = err.payload as RetryDocumentResult | undefined;
      setError(payload?.structuredResult?.error?.message || String(err.message || err));
    } finally {
      setRetryingDocument(false);
    }
  }

  async function saveActive() {
    if (!active?.importacion?.id) return;
    setSaving(true);
    setError('');
    setSavedMessage('');
    try {
      const result = await requestJson<SaveRevisionResult>('/api/save-importation', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          propuestaId: active.importacion.id,
          version: active.importacion.version,
          hashSha256: active.importacion.hash_sha256,
          cabecera: headerDraft,
          lineas: linesDraft,
        }),
      });
      const saved = result.structuredResult;
      if (saved?.importacion && saved.propuesta) {
        const updated: DocumentResult = mergeSavedRevision(active, saved.propuesta, saved.importacion);
        setStoredDocs((current) => [updated, ...current.filter((item) => item.importacion?.id !== updated.importacion?.id)]);
        setActiveIndex(0);
        setHeaderDraft({ ...(updated.cabecera || {}) });
        setLinesDraft((updated.lineas || []).map((line) => ({ ...line })));
      }
      setSavedMessage(`Revision guardada. Version ${result.structuredResult?.importacion?.version || ''}`);
    } catch (err: any) {
      const payload = err.payload as SaveRevisionResult | undefined;
      setError(cleanIssueText(payload?.structuredResult?.error?.message || String(err.message || err)));
    } finally {
      setSaving(false);
    }
  }

  async function deleteActive() {
    if (!active?.importacion?.id) return;
    const name = sourceFile?.name || active.importacion.id;
    const confirmed = await onAskConfirm({
      title: 'Borrar revisión',
      message: `¿Desea borrar la revisión ${name}?`,
      confirmText: 'Borrar',
      variant: 'danger',
    });
    if (!confirmed) return;
    setDeletingRevision(true);
    setError('');
    setSavedMessage('');
    try {
      await requestJson<DeleteRevisionResult>('/api/delete-importation', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          propuestaId: active.importacion.id,
          version: active.importacion.version,
          hashSha256: active.importacion.hash_sha256,
        }),
      });
      const deletedId = String(active.importacion.id);
      setDeletedImportationIds((current) => {
        const next = new Set(current);
        next.add(deletedId);
        return next;
      });
      setStoredDocs((current) => current.filter((item) => String(item.importacion?.id || '') !== deletedId));
      setActiveIndex((index) => Math.max(0, index - 1));
      setSavedMessage('Revision borrada.');
    } catch (err: any) {
      const payload = err.payload as DeleteRevisionResult | undefined;
      setError(payload?.structuredResult?.error?.message || String(err.message || err));
    } finally {
      setDeletingRevision(false);
    }
  }

  return (
    <section className="panel reviewPanel">
      <header className="panelHeader compactHeader reviewHeader">
        <div>
          <span className="eyebrow">Revision</span>
          <h2>Propuestas de importacion</h2>
        </div>
        <span>{loadingStored ? 'cargando...' : `${reviewDocs.length} visibles · ${storedTotal} guardadas`}</span>
      </header>
      <div className="reviewSearchBar">
        <label>
          <Search size={16} />
          <input
            value={reviewSearch}
            onChange={(event) => {
              setReviewSearch(event.target.value);
              setReviewOffset(0);
            }}
            placeholder="Buscar factura, albaran, ruta o propuesta"
          />
        </label>
        <label><input type="checkbox" checked={showConfirmed} onChange={(event) => { setShowConfirmed(event.target.checked); setReviewOffset(0); }} /> Confirmadas / archivadas</label>
        <button type="button" disabled={reviewOffset <= 0 || loadingStored} onClick={() => setReviewOffset(Math.max(0, reviewOffset - reviewLimit))}>
          Anterior
        </button>
        <button type="button" disabled={reviewOffset + reviewLimit >= storedTotal || loadingStored} onClick={() => setReviewOffset(reviewOffset + reviewLimit)}>
          Siguiente
        </button>
      </div>
      {!reviewDocs.length && loadingStored ? (
        <div className="emptyPreview">
          <RefreshCw size={42} />
          <strong>Cargando propuestas de revision</strong>
          <span>Buscando propuestas guardadas para mostrar.</span>
        </div>
      ) : !reviewDocs.length ? (
        <div className="emptyPreview">
          <CheckCircle2 size={42} />
          <strong>Sin documentos pendientes de revision</strong>
          <span>{storedError || 'No hay propuestas revisables guardadas ni en la ultima ejecucion.'}</span>
        </div>
      ) : (
        <div className="reviewDesk">
          <aside className="reviewList">
            {reviewDocs.map((item, index) => {
              const name = item.pdf?.split(/[\\/]/).pop() || `documento ${index + 1}`;
              return (
                <button className={index === activeIndex ? 'active' : ''} type="button" key={`${item.pdf}-${index}`} onClick={() => setActiveIndex(index)}>
                  <strong>{name}</strong>
                  <small>{item.estado || 'propuesta'} · {item.importacion?.id || 'sin propuesta'}</small>
                </button>
              );
            })}
          </aside>
          <section className="reviewViewer">
            <div className="viewerTools">
              <span>{sourceFile?.name || 'Sin documento'}</span>
              <span className="reviewState">{active?.estado || 'propuesta'}</span>
              {sourceFile?.kind === 'pdf' && (
                <div className="pageStepper">
                  <button type="button" disabled={reviewPage <= 1} onClick={() => setReviewPage((page) => Math.max(1, page - 1))} title="Pagina anterior">
                    <ChevronLeft size={15} />
                  </button>
                  <span>{reviewPage}/{pageTotal}</span>
                  <button type="button" disabled={reviewPage >= pageTotal} onClick={() => setReviewPage((page) => Math.min(pageTotal, page + 1))} title="Pagina siguiente">
                    <ChevronRight size={15} />
                  </button>
                </div>
              )}
              {sourceFile && (
                <a className="smallButton" href={sourceFile.url} target="_blank" rel="noreferrer">
                  <Maximize2 size={15} /> Abrir
                </a>
              )}
            </div>
            <Preview file={sourceFile} zoom={88} page={reviewPage} />
          </section>
          <section className="reviewData">
            {storedError && <div className="resultBox warning"><strong>No se pudieron cargar propuestas</strong><span>{storedError}</span></div>}
            <div className="reviewTiles">
              <div className={`summaryTile ${active?.validacion?.can_create_entry === false ? 'error' : 'ok'}`}>
                <span>Validacion</span>
                <strong>{active?.validacion?.can_create_entry === false ? 'Revisar' : 'Confirmable'}</strong>
              </div>
              <div className="summaryTile article">
                <span>Total doc.</span>
                <strong>{String(active?.totales?.source_gross ?? '?')}</strong>
              </div>
              <div className="summaryTile document">
                <span>Calculado</span>
                <strong>{String(active?.totales?.computed_gross ?? '?')}</strong>
              </div>
            </div>
            <div className="issueList">
              {activeIssues.map((issue) => <span key={issue}>{issue}</span>)}
            </div>
            <div className="reviewForm">
              <div className="fieldGrid">
                {[
                  ['proveedor', 'Proveedor'],
                  ['nombre_proveedor', 'Nombre'],
                  ['cif', 'CIF'],
                  ['centro', 'Centro'],
                  ['factura', 'Factura'],
                  ['albaran', 'Albaran'],
                  ['fecha_factura', 'Fecha factura'],
                  ['fecha', 'Fecha entrada'],
                ].map(([field, label]) => (
                  <label key={field}>
                    <span>{label}</span>
                    <input value={textValue(headerDraft[field])} onChange={(event) => setHeaderField(field, event.target.value)} />
                  </label>
                ))}
              </div>
              <div className="fieldGrid">
                <label><span>Total del documento comprobado</span>
                  <input value={textValue(headerDraft.total_documento)} onChange={(event) => setHeaderField('total_documento', event.target.value)} placeholder="Opcional: total leido en el original" />
                </label>
                <label><span>Politica de precios de compra</span>
                  <select value={textValue(headerDraft.politica_precio_compra) || 'mantener'} onChange={(event) => setHeaderField('politica_precio_compra', event.target.value)}>
                    <option value="mantener">Mantener</option><option value="actualizar">Actualizar</option><option value="actualizar_si_sube">Actualizar solo si sube</option>
                  </select>
                </label>
              </div>
              {active?.validacion?.source_total_detected === false && <label>
                <input type="checkbox" checked={headerDraft.confirmar_sin_total === true} onChange={(event) => setHeaderDraft((current) => ({ ...current, confirmar_sin_total: event.target.checked }))} />
                He revisado todas las lineas; el documento no informa un total contrastable.
              </label>}
              {active?.validacion?.evidence_low_confidence === true && <label>
                <input type="checkbox" checked={headerDraft.evidencia_revisada === true} onChange={(event) => setHeaderDraft((current) => ({ ...current, evidencia_revisada: event.target.checked }))} />
                He contrastado la lectura de baja confianza con el original.
              </label>}
              {isDocumentOnly && <p>Esta propuesta solo archiva el documento; no genera entradas ni stock.</p>}
              {draftDirty && <p>Guarda la revision para validar los cambios antes de confirmar.</p>}
            </div>
            <div className="lineEditor">
              <div className="lineEditorHeader">
                <strong>Lineas</strong>
                <button type="button" onClick={() => setLinesDraft((current) => [...current, emptyReviewLine()])}>
                  <FilePlus2 size={15} /> Añadir
                </button>
              </div>
              <div className="lineTable">
                <div className="lineTableHead">
                  <span>Ref. proveedor</span>
                  <span>Articulo</span>
                  <span>Descripcion</span>
                  <span>Cant.</span>
                  <span>Precio</span>
                  <span>Dto.</span>
                  <span>IVA</span>
                  <span>Importe</span>
                  <span>Sel.</span>
                  <span></span>
                </div>
                {linesDraft.map((line, index) => {
                  const unresolvedLine = !textValue(line.articulo).trim();
                  return (
                  <div className={`lineTableRow ${unresolvedLine ? 'unresolved' : ''}`} key={index}>
                    <input value={textValue(line.referencia_proveedor)} onChange={(event) => setLineField(index, 'referencia_proveedor', event.target.value)} />
                    <input value={textValue(line.articulo)} onChange={(event) => setLineField(index, 'articulo', event.target.value)} />
                    <input value={textValue(line.descripcion)} onChange={(event) => setLineField(index, 'descripcion', event.target.value)} />
                    <input value={textValue(line.cantidad)} onChange={(event) => setLineField(index, 'cantidad', event.target.value)} />
                    <input value={textValue(line.precio)} onChange={(event) => setLineField(index, 'precio', event.target.value)} />
                    <input value={textValue(line.descuento1)} onChange={(event) => setLineField(index, 'descuento1', event.target.value)} />
                    <input value={textValue(line.iva)} onChange={(event) => setLineField(index, 'iva', event.target.value)} />
                    <input value={textValue(line.importe_origen)} onChange={(event) => setLineField(index, 'importe_origen', event.target.value)} />
                    <select value={textValue(line.article_selection || line.seleccion_articulo)} onChange={(event) => setLineField(index, 'article_selection', event.target.value)}>
                      <option value="">Auto</option>
                      <option value="manual">Manual</option>
                    </select>
                    <button type="button" title="Quitar linea" onClick={() => setLinesDraft((current) => current.filter((_, lineIndex) => lineIndex !== index))}>
                      <Trash2 size={15} />
                    </button>
                  </div>
                  );
                })}
                {!linesDraft.length && <div className="lineTableEmpty">Sin lineas detectadas.</div>}
              </div>
            </div>
            <div className="reviewActions">
              <button
                type="button"
                disabled={!active?.importacion?.id || saving || confirming || retryingDocument || deletingRevision}
                onClick={() => saveActive()}
              >
                {saving ? 'Guardando...' : 'Guardar revisión'}
              </button>
              <button
                type="button"
                disabled={confirmBlocked || saving || confirming || retryingDocument || deletingRevision}
                title={confirmBlocked ? activeIssues[0] || 'No hay propuesta persistida confirmable' : 'Confirmar propuesta'}
                onClick={() => confirmActive()}
              >
                {confirming ? 'Confirmando...' : isDocumentOnly ? 'Archivar documento' : 'Confirmar propuesta'}
              </button>
              <button
                type="button"
                disabled={!documentRetryEnabled || saving || confirming || retryingDocument || deletingRevision}
                title={documentRetryEnabled ? 'Reintentar archivo documental' : 'Disponible tras confirmar la propuesta'}
                onClick={() => retryDocumentActive()}
              >
                {retryingDocument ? 'Reintentando...' : 'Reintentar archivo'}
              </button>
              <button
                type="button"
                className="dangerAction"
                disabled={!deleteRevisionEnabled || saving || confirming || retryingDocument || deletingRevision}
                title={deleteRevisionEnabled ? 'Borrar datos de revision' : 'No se pueden borrar propuestas confirmadas'}
                onClick={() => deleteActive()}
              >
                {deletingRevision ? 'Borrando...' : 'Borrar revisión'}
              </button>
              <small>{active?.importacion?.id ? `Propuesta ${active.importacion.id} · v${active.importacion.version || '?'}` : 'Sin propuesta persistida'}</small>
            </div>
            {savedMessage && <div className="resultBox ok"><strong>Guardado</strong><span>{savedMessage}</span></div>}
            {error && <div className="resultBox warning"><strong>No se pudo confirmar</strong><span>{error}</span></div>}
          </section>
        </div>
      )}
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
    aiFallback: false,
  });
  const [aiConfig, setAiConfig] = useState<AiConfig>(defaultAiConfig());
  const [showAiConfig, setShowAiConfig] = useState(false);
  const [savingAiConfig, setSavingAiConfig] = useState(false);
  const [aiConfigError, setAiConfigError] = useState('');
  const [showAiFallbackConfirm, setShowAiFallbackConfirm] = useState(false);
  const aiFallbackConfirmResolver = useRef<((value: boolean) => void) | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<ConfirmDialogState | null>(null);
  const confirmDialogResolver = useRef<((value: boolean | string | null) => void) | null>(null);
  const [activeLog, setActiveLog] = useState<LogItem | undefined>();
  const [search, setSearch] = useState('');
  const [running, setRunning] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [zoom, setZoom] = useState(82);
  const [columnsView, setColumnsView] = useState(false);
  const [mainTab, setMainTab] = useState<'principal' | 'revision' | 'logs' | 'archivo'>('principal');
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState<Notice | null>(null);

  async function refresh() {
    const next = await requestJson<AppState>('/api/state');
    setState(next);
    if (next.aiConfig) {
      const normalized = normalizeAiConfig(next.aiConfig);
      setAiConfig(normalized);
    }
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
    const confirmed = await askConfirm({
      title: 'Borrar pendientes',
      message: `¿Desea borrar ${label} de Pendientes?`,
      confirmText: 'Borrar',
      variant: 'danger',
    });
    if (!confirmed) return;
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

  function askAiFallbackConfirmation() {
    setShowAiFallbackConfirm(true);
    return new Promise<boolean>((resolve) => {
      aiFallbackConfirmResolver.current = resolve;
    });
  }

  function resolveAiFallbackConfirmation(value: boolean) {
    aiFallbackConfirmResolver.current?.(value);
    aiFallbackConfirmResolver.current = null;
    setShowAiFallbackConfirm(false);
  }

  function askConfirm(dialog: ConfirmDialogState) {
    setConfirmDialog(dialog);
    return new Promise<boolean>((resolve) => {
      confirmDialogResolver.current = (value) => resolve(value === true);
    });
  }

  function askChoice(dialog: ConfirmDialogState) {
    setConfirmDialog(dialog);
    return new Promise<string | null>((resolve) => {
      confirmDialogResolver.current = (value) => resolve(typeof value === 'string' ? value : null);
    });
  }

  function resolveConfirmDialog(value: boolean | string | null) {
    confirmDialogResolver.current?.(value);
    confirmDialogResolver.current = null;
    setConfirmDialog(null);
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
    const applyRunResult = (result: RunResult) => {
      setRunResult(result);
      if (result.state) setState(result.state);
      if (result.latestLog) setActiveLog(result.latestLog);
      if (Number(result.structuredResult?.requiere_revision || 0) > 0 || runHasConfirmableProposals(result)) setMainTab('revision');
      if (runHasConfirmableProposals(result)) {
        setNotice({
          title: 'Entrada no creada',
          message: 'No se ha creado la entrada de almacen porque este documento viene de IA y queda como propuesta revisable. Para integrarlo, confirma la propuesta en la pestaña Revision.',
          details: integrationReport(result),
          variant: 'info',
        });
      } else if (runHasIncidents(result)) {
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
    };
    const maybeAskForAi = async (result: RunResult) => {
      if (!processOptions.aiFallback || !runHasIncidents(result)) return result;
      const wantsAi = await askAiFallbackConfirmation();
      if (!wantsAi) return result;
      setMessage('Consultando IA para documentos pendientes...');
      const aiResult = await requestJson<RunResult>('/api/ai-fallback', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ result, mode: activeMode, missingPolicy: state.modes[activeMode]?.missingPolicy || 'detener' }),
      });
      return aiResult;
    };
    const runSelectedMode = (mode: string) => requestJson<RunResult>('/api/run', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ mode, selectedNames: names, aiFallback: false }),
    });
    const discardImportations = async (documents: DocumentResult[]) => {
      await Promise.all(documents.map(async (item) => {
        if (!item.importacion?.id || !item.importacion.version || !item.importacion.hash_sha256) return;
        try {
          await requestJson<DeleteRevisionResult>('/api/delete-importation', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({
              propuestaId: item.importacion.id,
              version: item.importacion.version,
              hashSha256: item.importacion.hash_sha256,
            }),
          });
        } catch {
          // If it was already deleted or changed, rerun will surface the current state.
        }
      }));
    };
    const maybeCreateMissingProviders = async (result: RunResult) => {
      const documents = missingProviderDocuments(result);
      if (!documents.length) return result;
      const action = await askChoice({
        title: 'Proveedor no encontrado',
        message: `El proveedor no existe en Faro: ${providerCreationSummary(documents)}. Elija si quiere grabar el proveedor, guardar solo en DOCUMENTO sin entrada de almacen, o detener sin hacer nada.`,
        actions: [
          { value: 'create_provider', label: 'Grabar el proveedor', style: 'primary' },
          { value: 'document_only', label: 'Guardar solo DOCUMENTO', style: 'secondary' },
          { value: 'stop', label: 'Detener', style: 'danger' },
        ],
      });
      if (action === 'document_only') {
        setMessage('Guardando solo en gestion documental...');
        await discardImportations(documents);
        return runSelectedMode('documental');
      }
      if (action !== 'create_provider') return result;
      setMessage('Dando de alta proveedor en Faro...');
      const created = await requestJson<CreateProvidersResult>('/api/providers/create-from-documents', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ documentos: documents }),
      });
      if (created.state) setState(created.state);
      const createdCount = Number(created.structuredResult?.creados?.length || 0);
      if (!createdCount) return result;
      setMessage('Proveedor creado. Reprocesando fichero...');
      await discardImportations(documents);
      return runSelectedMode(activeMode);
    };
    const maybeAskForGhostLines = async (result: RunResult) => {
      if (
        processOptions.documentOnly
        || processOptions.ghostLines
        || activeMode === 'fantasma'
        || activeMode === 'fantasma_sube'
        || runHasProviderIncident(result)
        || runHasTotalMismatchIncident(result)
        || !runHasMissingArticleIncident(result)
      ) {
        return result;
      }
      const confirmed = await askConfirm({
        title: 'Grabar lineas fantasma',
        message: 'No se han encontrado uno o varios articulos. ¿Desea grabarlos como lineas fantasma?',
        confirmText: 'Grabar fantasma',
      });
      if (!confirmed) return result;
      setMessage('Integrando con lineas fantasma...');
      const ghostMode = processOptions.updateOnlyIfUp ? 'fantasma_sube' : 'fantasma';
      return runSelectedMode(ghostMode);
    };
    try {
      const result = await runSelectedMode(activeMode);
      const reviewedResult = await maybeAskForAi(result);
      const providerResult = await maybeCreateMissingProviders(reviewedResult);
      applyRunResult(await maybeAskForGhostLines(providerResult));
    } catch (err: any) {
      const payload = err.payload as RunResult | undefined;
      if (payload) {
        try {
          const reviewedPayload = await maybeAskForAi(payload);
          const providerPayload = await maybeCreateMissingProviders(reviewedPayload);
          applyRunResult(await maybeAskForGhostLines(providerPayload));
        } catch (aiErr: any) {
          const aiPayload = aiErr.payload as RunResult | undefined;
          if (aiPayload) applyRunResult(aiPayload);
          else {
            setRunResult(payload);
            if (payload.state) setState(payload.state);
            if (payload.latestLog) setActiveLog(payload.latestLog);
            if (Number(payload.structuredResult?.requiere_revision || 0) > 0) setMainTab('revision');
            setNotice({
              title: 'Integracion con incidencias',
              message: String(aiErr.message || aiErr),
              details: integrationReport(payload),
              variant: 'warning',
            });
          }
        }
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

  async function saveAiConfig(config: AiConfig) {
    setSavingAiConfig(true);
    setAiConfigError('');
    try {
      const result = await requestJson<{ ok: boolean; aiConfig: AiConfig }>('/api/ai-config', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(config),
      });
      const normalized = normalizeAiConfig(result.aiConfig);
      setAiConfig(normalized);
      setShowAiConfig(false);
      setMessage('Configuracion de IA guardada');
    } catch (err: any) {
      setAiConfigError(String(err.message || err));
    } finally {
      setSavingAiConfig(false);
    }
  }

  function applyConfirmResult(result: ConfirmResult) {
    if (result.state) setState(result.state);
    const pendingDeleted = result.structuredResult?.pendiente_borrado as Record<string, unknown> | undefined;
    const deletedSuffix = pendingDeleted?.borrado === true
      ? ' PDF eliminado de Pendientes.'
      : result.ok
        ? ' Atención: no consta borrado del PDF de Pendientes.'
        : '';
    setNotice({
      title: result.ok ? 'Propuesta confirmada' : 'Confirmacion con incidencias',
      message: result.ok
        ? `Entrada creada ${result.structuredResult?.documento?.ejercicio || ''}-${result.structuredResult?.documento?.serie || ''}-${result.structuredResult?.documento?.numero || ''}.${deletedSuffix}`
        : result.structuredResult?.error?.message || result.stderr || 'No se pudo confirmar la propuesta.',
      variant: result.ok ? 'info' : 'warning',
    });
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
        <button className={mainTab === 'revision' ? 'active' : ''} type="button" onClick={() => setMainTab('revision')}>
          Revisión
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
          <ToolbarButton icon={<Settings size={32} />} label="Configurar IA" active={showAiConfig} onClick={() => setShowAiConfig(true)} />
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
              <label className="checkOption">
                <input
                  type="checkbox"
                  checked={processOptions.aiFallback}
                  disabled={processOptions.documentOnly}
                  onChange={(event) => setProcessOptions((current) => ({ ...current, aiFallback: event.target.checked }))}
                />
                <span>
                  <strong>Preguntar IA si no integra</strong>
                  <small>{aiConfig.enabled ? `${aiConfig.provider} · ${aiConfig.model}` : 'Configura la llamada antes de procesar.'}</small>
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

      {mainTab === 'revision' && (
        <section className="tabPage">
          <ReviewPanel runResult={runResult} state={state} onConfirmed={applyConfirmResult} onAskConfirm={askConfirm} />
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
                    <li key={`${detail}-${index}`}>{highlightedNoticeDetail(detail)}</li>
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

      {showAiConfig && (
        <AiConfigDialog
          initialConfig={aiConfig}
          saving={savingAiConfig}
          error={aiConfigError}
          onCancel={() => setShowAiConfig(false)}
          onSave={saveAiConfig}
        />
      )}

      {showAiFallbackConfirm && (
        <ConfirmDialog
          title="Usar IA para esta integracion"
          message="La integracion directa ha dejado incidencias. ¿Desea intentar extraer los documentos pendientes con IA?"
          confirmText="Usar IA"
          onCancel={() => resolveAiFallbackConfirmation(false)}
          onConfirm={() => resolveAiFallbackConfirmation(true)}
        />
      )}

      {confirmDialog && (
        <ConfirmDialog
          {...confirmDialog}
          onCancel={() => resolveConfirmDialog(false)}
          onConfirm={() => resolveConfirmDialog(true)}
          onAction={(value) => resolveConfirmDialog(value)}
        />
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
