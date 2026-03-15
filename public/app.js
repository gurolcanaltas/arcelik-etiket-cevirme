const uploadForm = document.querySelector("#upload-form");
const pdfInput = document.querySelector("#pdf-input");
const statusEl = document.querySelector("#status");
const editorPanel = document.querySelector("#editor-panel");
const resultTitle = document.querySelector("#result-title");
const summary = document.querySelector("#summary");
const pagesContainer = document.querySelector("#pages");
const downloadBtn = document.querySelector("#download-btn");

let currentAnalysis = null;
let currentPageModels = [];
let pageStates = new Map();

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  if (!pdfInput.files.length) {
    setStatus("Lutfen bir PDF secin.");
    return;
  }

  const formData = new FormData();
  formData.append("pdf", pdfInput.files[0]);
  setStatus("PDF inceleniyor...");
  downloadBtn.disabled = true;

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      body: formData
    });
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.error || "PDF incelenemedi.");
    }

    currentAnalysis = payload;
    currentPageModels = payload.pages.map(buildPageModel).filter((pageModel) => pageModel.hasAnyFields);
    pageStates = new Map(currentPageModels.map((pageModel) => [pageModel.pageNumber, createPageState(pageModel)]));
    renderAnalysis();
    setStatus("PDF hazir. Sayfa bazli fiyat donusum secenekleri yuklendi.");
  } catch (error) {
    console.error(error);
    setStatus(error.message);
  }
});

downloadBtn.addEventListener("click", async () => {
  if (!currentAnalysis) {
    return;
  }

  const { replacements, templateTransforms, problems } = collectSubmission();
  if (problems.length) {
    setStatus(problems[0]);
    return;
  }

  if (!replacements.length && !templateTransforms.length) {
    setStatus("Kaydedilecek bir degisiklik bulunamadi.");
    return;
  }

  setStatus("PDF guncelleniyor...");
  downloadBtn.disabled = true;

  try {
    const response = await fetch("/api/replace", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: currentAnalysis.source,
        replacements,
        templateTransforms
      })
    });

    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.error || "PDF guncellenemedi.");
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `duzenlenmis-${currentAnalysis.fileName}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setStatus("Guncellenmis PDF indirildi.");
  } catch (error) {
    console.error(error);
    setStatus(error.message);
  } finally {
    downloadBtn.disabled = false;
  }
});

function derivePageMeta(page) {
  const candidates = dedupeExactEntries(page.entries
    .filter((entry) => entry.bbox && entry.originalText)
    .map((entry) => ({ ...entry, text: normalizeWhitespace(entry.originalText) }))
    .filter((entry) => entry.text))
    .sort((left, right) => (left.bbox?.[1] ?? 0) - (right.bbox?.[1] ?? 0));

  const titleEntry = candidates.find((entry) => {
    return entry.alignment === "center"
      && (entry.bbox?.[1] ?? 999) <= 42
      && entry.text.length >= 3
      && entry.text.length <= 36
      && /[\p{L}\d]/u.test(entry.text)
      && !/^[.,\s]+$/u.test(entry.text);
  }) || null;

  const typeEntry = candidates.find((entry) => {
    return entry.alignment === "center"
      && (entry.bbox?.[1] ?? 999) > 42
      && (entry.bbox?.[1] ?? 999) <= 120
      && entry.text.length >= 6
      && entry.text.length <= 48
      && /\p{L}/u.test(entry.text)
      && !/\d/.test(entry.text);
  }) || null;

  return { titleEntry, typeEntry };
}

function deriveDateField(page) {
  const entries = page.entries
    .filter((entry) => entry.bbox && entry.originalText)
    .map((entry) => ({ ...entry, text: normalizeWhitespace(entry.originalText) }))
    .sort((left, right) => (left.bbox?.[1] ?? 0) - (right.bbox?.[1] ?? 0) || (left.bbox?.[0] ?? 0) - (right.bbox?.[0] ?? 0));

  const labelEntry = entries.find((entry) => stripDiacritics(entry.text.toUpperCase()).includes("FIYAT DEGISIKLIK TARIHI"));
  if (!labelEntry) {
    return null;
  }

  const sameLineEntries = entries
    .filter((entry) => Math.abs((entry.bbox?.[1] ?? 0) - (labelEntry.bbox?.[1] ?? 0)) <= 1.5)
    .sort((left, right) => (left.bbox?.[0] ?? 0) - (right.bbox?.[0] ?? 0));

  const labelText = normalizeWhitespace(labelEntry.originalText);
  const normalizedLabelText = stripDiacritics(labelText.toLowerCase());
  const marker = 'fiyat degisiklik tarihi';
  const markerIndex = normalizedLabelText.indexOf(marker);
  const splitIndex = markerIndex === -1 ? -1 : markerIndex + marker.length;
  const labelPrefix = splitIndex === -1 ? labelText : labelText.slice(0, splitIndex).trimEnd() + ' ';
  const labelDatePart = splitIndex === -1 ? '' : normalizeWhitespace(labelText.slice(splitIndex));

  const dateSegments = [];
  if (labelDatePart && containsDigit(labelDatePart)) {
    dateSegments.push({
      id: labelEntry.id,
      originalText: labelDatePart,
      prefix: labelPrefix
    });
  }

  for (const entry of sameLineEntries) {
    if (entry.id === labelEntry.id) {
      continue;
    }
    if ((entry.bbox?.[0] ?? 0) < (labelEntry.bbox?.[0] ?? 0)) {
      continue;
    }
    const textValue = normalizeWhitespace(entry.originalText);
    if (!isDateFragment(textValue)) {
      continue;
    }
    dateSegments.push({
      id: entry.id,
      originalText: textValue,
      prefix: ''
    });
  }

  if (!dateSegments.length) {
    return null;
  }

  const dateValue = dateSegments.map((segment) => segment.originalText).join('');
  if (!isFullDate(dateValue)) {
    return null;
  }

  return {
    key: 'change-date',
    label: 'Tarih',
    originalValue: dateValue,
    hint: 'PDF alt bilgisindeki fiyat degisiklik tarihi',
    transform: 'plain',
    projection: 'split',
    prefix: '',
    segments: dateSegments
  };
}

function derivePricingModel(page) {
  const normalizedEntries = page.entries
    .filter((entry) => entry.bbox && entry.originalText)
    .map((entry) => ({ ...entry, text: normalizeWhitespace(entry.originalText) }));

  const headers = locatePriceHeaders(page, normalizedEntries);
  if (!headers) {
    return {
      pricingMode: "Fiyat bulunamadi",
      headlinePriceFields: [],
      installmentPlans: []
    };
  }

  const headlinePriceFields = buildHeadlinePriceFields(page, normalizedEntries, headers);
  const installmentPlans = buildInstallmentPlans(page, normalizedEntries, headers);

  return {
    pricingMode: headlinePriceFields.length > 1 ? "Parolu" : "Duz Fiyat",
    headlinePriceFields,
    installmentPlans
  };
}

function locatePriceHeaders(page, entries) {
  const priceHeaderEntries = entries.filter((entry) => isHeaderText(entry.text));
  if (!priceHeaderEntries.length) {
    return null;
  }

  const mergedHeader = priceHeaderEntries.find((entry) => entry.text.includes("PEŞİNAT") && entry.text.includes("TAKSİT") && entry.text.includes("TOPLAM"));
  if (mergedHeader) {
    return {
      headerY: mergedHeader.bbox[1],
      columnXs: {
        pesinat: page.width * 0.2,
        taksit: page.width * 0.5,
        toplam: page.width * 0.8
      }
    };
  }

  const pesinat = priceHeaderEntries.find((entry) => entry.text.includes("PEŞİNAT"));
  const taksit = priceHeaderEntries.find((entry) => entry.text.includes("TAKSİT"));
  const toplam = priceHeaderEntries.find((entry) => entry.text.includes("TOPLAM"));

  if (!pesinat || !taksit || !toplam) {
    return null;
  }

  return {
    headerY: Math.min(pesinat.bbox[1], taksit.bbox[1], toplam.bbox[1]),
    columnXs: {
      pesinat: pesinat.bbox[0],
      taksit: taksit.bbox[0],
      toplam: toplam.bbox[0]
    }
  };
}

function buildHeadlinePriceFields(page, entries, headers) {
  const topAreaEntries = entries
    .filter((entry) => entry.editable)
    .filter((entry) => isNumericFragment(entry.text))
    .filter((entry) => entry.bbox[1] >= headers.headerY - 75 && entry.bbox[1] <= headers.headerY - 10);

  const rows = groupByY(topAreaEntries, 4);
  const primaryRow = rows.sort((left, right) => right.length - left.length || averageY(left) - averageY(right))[0] || [];
  const clusters = clusterByX(primaryRow, 24)
    .map((cluster) => ({
      entries: cluster,
      text: joinPriceParts(cluster),
      x: cluster[0]?.bbox[0] ?? 0,
      distanceToCenter: Math.abs((cluster[0]?.bbox[0] ?? 0) - page.width / 2)
    }))
    .filter((cluster) => isNumericPrice(cluster.text));

  const uniqueClusters = dedupeClustersByText(clusters);
  const footerClusters = dedupeClustersByText(collectFooterSummaryClusters(entries, headers));
  const fieldDefs = [];

  if (uniqueClusters.length === 1) {
    const topCluster = uniqueClusters[0];
    const matchingFooter = footerClusters.find((cluster) => cluster.text === topCluster.text);

    fieldDefs.push({
      key: "main-price",
      label: "Ana Fiyat",
      hint: matchingFooter ? "Ust ve alt ana fiyat kutulari" : "Ust fiyat kutusundaki ana fiyat",
      entries: [...topCluster.entries, ...(matchingFooter?.entries || [])]
    });

    const distinctFooter = footerClusters.find((cluster) => cluster.text !== topCluster.text);
    if (distinctFooter) {
      fieldDefs.push({
        key: "cash-price",
        label: "Nakit Fiyati",
        hint: "Alt ozet fiyat kutusu",
        entries: distinctFooter.entries
      });
    }
  } else if (uniqueClusters.length >= 2) {
    const orderedTop = uniqueClusters.slice(0, 2).sort((left, right) => left.x - right.x);
    const orderedFooter = footerClusters.slice(0, 2).sort((left, right) => left.x - right.x);

    fieldDefs.push({
      key: "main-price",
      label: "Ana Fiyat",
      hint: "Sol ana fiyat kutusu",
      entries: [...orderedTop[0].entries, ...(orderedFooter[0]?.entries || [])]
    });
    fieldDefs.push({
      key: "parolu-price",
      label: "Parolu Fiyat",
      hint: "Sag parolu fiyat kutusu",
      entries: [...orderedTop[1].entries, ...(orderedFooter[1]?.entries || [])]
    });
  }

  return fieldDefs
    .map((field) => buildSegmentField(field.key, field.label, field.entries, { hint: field.hint }))
    .filter(Boolean);
}

function collectFooterSummaryClusters(entries, headers) {
  const footerLabelY = entries
    .filter((entry) => entry.bbox[1] > headers.headerY)
    .filter((entry) => /(NAKIT|PESIN) FIYATI/u.test(stripDiacritics(entry.text.toUpperCase())))
    .map((entry) => entry.bbox[1])
    .sort((left, right) => left - right)[0];

  if (!Number.isFinite(footerLabelY)) {
    return [];
  }

  const buildClusters = (fromY, toY) => {
    const footerEntries = entries
      .filter((entry) => entry.editable)
      .filter((entry) => isNumericFragment(entry.text))
      .filter((entry) => entry.bbox[1] >= fromY && entry.bbox[1] <= toY);

    const footerRows = groupByY(footerEntries, 4);
    const footerRow = footerRows.sort((left, right) => right.length - left.length || averageY(left) - averageY(right))[0] || [];

    return clusterByX(footerRow, 24)
      .map((cluster) => ({
        entries: cluster,
        text: joinPriceParts(cluster),
        x: cluster[0]?.bbox[0] ?? 0,
        distanceToCenter: 0
      }))
      .filter((cluster) => isNumericPrice(cluster.text));
  };

  const belowClusters = buildClusters(footerLabelY + 6, footerLabelY + 26);
  if (belowClusters.length >= 1 && belowClusters.length <= 2) {
    return belowClusters;
  }

  const aboveClusters = buildClusters(footerLabelY - 26, footerLabelY - 6);
  if (aboveClusters.length >= 1 && aboveClusters.length <= 2) {
    return aboveClusters;
  }

  return [];
}

function buildInstallmentPlans(page, entries, headers) {
  const footerLabelY = entries
    .filter((entry) => entry.bbox[1] > headers.headerY)
    .filter((entry) => /(NAKIT|PESIN) FIYATI/u.test(stripDiacritics(entry.text.toUpperCase())))
    .map((entry) => entry.bbox[1])
    .sort((left, right) => left - right)[0] ?? Number.POSITIVE_INFINITY;

  const rowEntries = entries
    .filter((entry) => entry.editable)
    .filter((entry) => entry.bbox[1] >= headers.headerY + 8 && entry.bbox[1] < footerLabelY - 4)
    .filter((entry) => isNumericFragment(entry.text) || isInstallmentFragment(entry.text));

  const rowGroups = groupByY(rowEntries, 4);
  const plans = [];

  for (const rowGroup of rowGroups) {
    const columns = { pesinat: [], taksit: [], toplam: [] };

    for (const entry of rowGroup.sort((left, right) => left.bbox[0] - right.bbox[0])) {
      const columnName = nearestColumn(entry, headers.columnXs);
      columns[columnName].push(entry);
    }

    const taksitCombined = joinPriceParts(dedupeExactEntries(columns.taksit));
    const planInfo = parseInstallmentPlan(taksitCombined);

    if (!planInfo) {
      continue;
    }

    const pesinatField = buildSegmentField(`${planInfo.label}-pesinat`, `${planInfo.label} Pesinat`, columns.pesinat, {
      hint: `${planInfo.label} planinin pesinat tutari`
    });
    const taksitField = buildSegmentField(`${planInfo.label}-taksit`, `${planInfo.label} Taksit`, columns.taksit, {
      hint: `${planInfo.label} planinin taksit tutari`,
      prefix: planInfo.prefix,
      displayValue: planInfo.amount
    });
    const toplamField = buildSegmentField(`${planInfo.label}-toplam`, `${planInfo.label} Toplam`, columns.toplam, {
      hint: `${planInfo.label} planinin toplam fiyati`
    });

    if (pesinatField && taksitField && toplamField) {
      plans.push({
        order: planInfo.installmentCount,
        label: planInfo.label,
        fields: [pesinatField, taksitField, toplamField]
      });
    }
  }

  return plans.sort((left, right) => left.order - right.order);
}

function buildSingleField(key, label, entry, hint) {
  return {
    key,
    label,
    originalValue: normalizeWhitespace(entry.originalText),
    hint,
    transform: "plain",
    prefix: "",
    segments: [{
      id: entry.id,
      originalText: normalizeWhitespace(entry.originalText)
    }]
  };
}

function buildSegmentField(key, label, entries, options = {}) {
  const orderedEntries = entries
    .filter(Boolean)
    .slice()
    .sort((left, right) => left.bbox[0] - right.bbox[0]);

  if (!orderedEntries.length) {
    return null;
  }

  const originalValue = options.displayValue ?? (shouldMirrorSegments(orderedEntries) ? normalizeWhitespace(orderedEntries[0].originalText || orderedEntries[0].text || "") : joinPriceParts(orderedEntries));
  return {
    key,
    label,
    originalValue,
    hint: options.hint || "PDF fiyat alani",
    transform: options.prefix ? "prefixed" : "plain",
    projection: shouldMirrorSegments(orderedEntries) ? "mirror" : "split",
    prefix: options.prefix || "",
    segments: orderedEntries.map((entry) => ({
      id: entry.id,
      originalText: normalizeWhitespace(entry.originalText)
    }))
  };
}

function collectReplacements() {
  const replacements = [];
  const problems = [];
  const seen = new Map();
  const cards = document.querySelectorAll(".field-card");

  for (const card of cards) {
    const field = JSON.parse(card.dataset.field);
    const input = card.querySelector(".field-input");
    const nextValue = normalizeWhitespace(input.value);
    const currentValue = normalizeWhitespace(field.originalValue);

    if (!nextValue) {
      problems.push(`${field.label} bos birakilamaz.`);
      continue;
    }

    if (nextValue === currentValue) {
      continue;
    }

    const operations = buildReplacementOperations(field, nextValue);
    if (!operations.length) {
      problems.push(`${field.label} icin metin parcasi uretilemedi.`);
      continue;
    }

    for (const operation of operations) {
      seen.set(operation.id, operation.replacementText);
    }
  }

  for (const [id, replacementText] of seen.entries()) {
    replacements.push({ id, replacementText });
  }

  return { replacements, problems };
}

function buildReplacementOperations(field, nextValue) {
  const fullValue = field.transform === "prefixed" ? `${field.prefix}${nextValue}` : nextValue;
  const projected = field.projection === "mirror"
    ? field.segments.map(() => fullValue)
    : projectTextToSegments(field.segments.map((segment) => segment.originalText), fullValue);

  if (!projected) {
    return [];
  }

  return field.segments.map((segment, index) => ({
    id: segment.id,
    replacementText: `${segment.prefix || ""}${projected[index]}${segment.suffix || ""}`
  }));
}

function projectTextToSegments(originalParts, nextValue) {
  if (!originalParts.length) {
    return null;
  }

  if (originalParts.length === 1) {
    return [nextValue];
  }

  const projected = [];
  let cursor = 0;

  for (let index = 0; index < originalParts.length; index += 1) {
    const originalPart = originalParts[index];

    if (index === originalParts.length - 1) {
      projected.push(nextValue.slice(cursor));
      break;
    }

    const sliceLength = originalPart.length;
    projected.push(nextValue.slice(cursor, cursor + sliceLength));
    cursor += sliceLength;
  }

  return projected.every((part) => part.length > 0) ? projected : null;
}

function dedupeClustersByText(clusters) {
  const byText = new Map();

  for (const cluster of clusters) {
    const key = cluster.text;
    const bucket = byText.get(key) || [];
    bucket.push(cluster);
    byText.set(key, bucket);
  }

  return [...byText.values()].map((bucket) => {
    const preferred = bucket.slice().sort(compareClusterPriority)[0];
    const mergedEntries = [];
    const seenIds = new Set();

    for (const cluster of bucket) {
      for (const entry of cluster.entries) {
        if (seenIds.has(entry.id)) {
          continue;
        }
        seenIds.add(entry.id);
        mergedEntries.push(entry);
      }
    }

    return {
      ...preferred,
      entries: mergedEntries
    };
  });
}

function shouldMirrorSegments(entries) {
  if (entries.length <= 1) {
    return false;
  }

  const firstText = normalizeWhitespace(entries[0].originalText || entries[0].text || "");
  return entries.every((entry) => normalizeWhitespace(entry.originalText || entry.text || "") === firstText);
}

function compareClusterPriority(left, right) {
  const leftScore = clusterPriorityScore(left);
  const rightScore = clusterPriorityScore(right);
  return leftScore - rightScore || left.distanceToCenter - right.distanceToCenter || left.x - right.x;
}

function clusterPriorityScore(cluster) {
  const alignments = cluster.entries.map((entry) => entry.alignment);
  if (alignments.includes("center")) {
    return 0;
  }
  if (alignments.includes("right")) {
    return 1;
  }
  return 2;
}

function parseInstallmentPlan(taksitText) {
  const compact = taksitText.replace(/\s+/g, "");
  const match = compact.match(/^(\d+)x(.+)$/i);
  if (!match) {
    return null;
  }

  const installmentCount = Number(match[1]);
  if (!Number.isFinite(installmentCount)) {
    return null;
  }

  return {
    installmentCount,
    label: `1+${installmentCount}`,
    prefix: `${installmentCount}x`,
    amount: match[2]
  };
}

function nearestColumn(entry, columnXs) {
  const distances = Object.entries(columnXs)
    .map(([name, x]) => ({ name, distance: Math.abs(entry.bbox[0] - x) }))
    .sort((left, right) => left.distance - right.distance);
  return distances[0].name;
}

function groupByY(entries, tolerance) {
  const groups = [];

  for (const entry of entries.slice().sort((left, right) => left.bbox[1] - right.bbox[1] || left.bbox[0] - right.bbox[0])) {
    const lastGroup = groups[groups.length - 1];
    if (!lastGroup || Math.abs(lastGroup[0].bbox[1] - entry.bbox[1]) > tolerance) {
      groups.push([entry]);
      continue;
    }
    lastGroup.push(entry);
  }

  return groups;
}

function clusterByX(entries, gap) {
  const clusters = [];

  for (const entry of entries.slice().sort((left, right) => left.bbox[0] - right.bbox[0])) {
    const currentCluster = clusters[clusters.length - 1];
    if (!currentCluster) {
      clusters.push([entry]);
      continue;
    }

    const previousEntry = currentCluster[currentCluster.length - 1];
    const previousRight = previousEntry.bbox[2] ?? previousEntry.bbox[0];
    const shouldSplitFullPrice = isNumericPrice(normalizeWhitespace(previousEntry.originalText || previousEntry.text || ""))
      && isNumericPrice(normalizeWhitespace(entry.originalText || entry.text || ""))
      && normalizeWhitespace(previousEntry.originalText || previousEntry.text || "").length >= 4
      && normalizeWhitespace(entry.originalText || entry.text || "").length >= 4;

    if (entry.bbox[0] - previousRight > gap || shouldSplitFullPrice) {
      clusters.push([entry]);
    } else {
      currentCluster.push(entry);
    }
  }

  return clusters;
}

function averageY(entries) {
  return entries.reduce((sum, entry) => sum + entry.bbox[1], 0) / Math.max(entries.length, 1);
}

function isHeaderText(text) {
  return text.includes("PEŞİNAT") || text.includes("TAKSİT") || text.includes("TOPLAM");
}

function isNumericFragment(text) {
  return /^[\d.]+$/u.test(text);
}

function isDateFragment(text) {
  const value = normalizeWhitespace(text);
  return /^\d{1,4}[./-]?$/.test(value) || /^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$/.test(value) || /^[./-]$/.test(value);
}

function containsDigit(text) {
  return /\d/.test(text);
}

function isFullDate(text) {
  return /^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$/.test(normalizeWhitespace(text));
}

function isInstallmentFragment(text) {
  return /^(\d+)x[\d.]*$/iu.test(text) || /^[\d.]+$/u.test(text);
}

function isNumericPrice(text) {
  return /^[\d.]+$/u.test(text);
}

function joinPriceParts(entries) {
  return entries
    .map((entry) => normalizeWhitespace(entry.originalText || entry.text || ""))
    .join("")
    .replace(/\s+/g, "")
    .trim();
}

function normalizeWhitespace(value) {
  return String(value || "").trim().replace(/\s+/g, " ");
}

function dedupeExactEntries(entries) {
  const seen = new Set();
  const uniqueEntries = [];

  for (const entry of entries) {
    const key = [
      Math.round((entry.bbox?.[0] ?? 0) * 10),
      Math.round((entry.bbox?.[1] ?? 0) * 10),
      normalizeWhitespace(entry.text || entry.originalText || "")
    ].join("|");

    if (seen.has(key)) {
      continue;
    }

    seen.add(key);
    uniqueEntries.push(entry);
  }

  return uniqueEntries;
}

function stripDiacritics(value) {
  return value.normalize("NFD").replace(/\p{Diacritic}/gu, "");
}

function setStatus(message) {
  statusEl.textContent = message;
}

























function old_legacy_renderAnalysis() {
  editorPanel.classList.remove("hidden");
  resultTitle.textContent = currentAnalysis.fileName;
  pagesContainer.innerHTML = "";

  let totalFields = 0;
  let activeTransforms = 0;

  for (const pageModel of currentPageModels) {
    const pageState = pageStates.get(pageModel.pageNumber);
    const rendered = getRenderedPage(pageModel, pageState);
    totalFields += rendered.totalFields;
    if (rendered.transformEnabled) {
      activeTransforms += 1;
    }
    pagesContainer.appendChild(renderPageModel(pageModel, pageState, rendered));
  }

  summary.textContent = `${currentPageModels.length} sayfada ${totalFields} alan hazirlandi.${activeTransforms ? ` ${activeTransforms} sayfada sablon donusumu aktif.` : ""}`;

  if (!pagesContainer.children.length) {
    pagesContainer.innerHTML = '<p class="empty-state">Bu PDF icin duzenlenebilir hedef alan bulunamadi.</p>';
  }

  downloadBtn.disabled = false;
}

function old_legacy_buildPageModel(page) {
  const meta = derivePageMeta(page);
  const pricing = derivePricingModel(page);
  const dateField = deriveDateField(page);
  const productionField = deriveProductionField(page);

  const identityFields = [];
  if (meta.titleEntry) {
    identityFields.push(buildSingleField("machine-name", "Makine Ismi", meta.titleEntry, "Ust bant urun kodu / ismi"));
  }
  if (meta.typeEntry) {
    identityFields.push(buildSingleField("machine-type", "Makine Turu", meta.typeEntry, "Makine turu"));
  }
  if (dateField) {
    identityFields.push(dateField);
  }
  if (productionField) {
    identityFields.push(productionField);
  }

  return {
    pageNumber: page.pageNumber,
    title: meta.titleEntry?.text || `Sayfa ${page.pageNumber}`,
    subtitle: meta.typeEntry?.text || `Sayfa ${page.pageNumber}`,
    identityFields,
    headlinePriceFields: pricing.headlinePriceFields,
    installmentPlans: pricing.installmentPlans,
    pricingMode: pricing.pricingMode,
    transformModel: buildTransformModel(pricing, dateField, productionField),
    hasAnyFields: identityFields.length + pricing.headlinePriceFields.length + pricing.installmentPlans.reduce((sum, plan) => sum + plan.fields.length, 0) > 0
  };
}

function buildTransformModel(pricing, dateField, productionField) {
  if (pricing.pricingMode === "Duz Fiyat" && pricing.headlinePriceFields.length >= 1) {
    const mainPrice = pricing.headlinePriceFields.find((field) => field.key === "main-price") || pricing.headlinePriceFields[0];
    const paroluVirtual = buildVirtualField("parolu-price-virtual", "Parolu Fiyat", "", "Parolu sablondaki sag fiyat kutusu");
    return {
      available: true,
      type: "normal-to-parolu",
      label: "Paro Var Mi?",
      helper: "Acarsan bu sayfa parolu fiyat sablonuna donecek.",
      note: "Normal fiyatli sayfalarda ek parolu fiyat kutusu acar.",
      dateField,
      productionField,
      extraFields: [paroluVirtual],
      headlinePriceFields: [mainPrice, paroluVirtual].filter(Boolean)
    };
  }

  if (pricing.pricingMode === "Parolu" && pricing.headlinePriceFields.length >= 1) {
    const mainPrice = pricing.headlinePriceFields.find((field) => field.key === "main-price") || pricing.headlinePriceFields[0];
    return {
      available: true,
      type: "parolu-to-normal",
      label: "Paro Bitti Mi?",
      helper: "Acarsan bu sayfa normal fiyat sablonuna donecek.",
      note: "Parolu fiyatli sayfalarda gereksiz fiyat alanlarini kapatir.",
      dateField,
      productionField,
      extraFields: [],
      headlinePriceFields: [mainPrice].filter(Boolean)
    };
  }

  return {
    available: false,
    extraFields: []
  };
}

function createPageState(pageModel) {
  const values = {};
  for (const field of getAllFields(pageModel)) {
    values[field.key] = field.originalValue;
  }
  for (const field of pageModel.transformModel.extraFields || []) {
    values[field.key] = field.originalValue;
  }
  return {
    transformEnabled: false,
    values
  };
}

function getRenderedPage(pageModel, pageState) {
  const transformEnabled = Boolean(pageState?.transformEnabled && pageModel.transformModel.available);
  const identityFields = pageModel.identityFields;
  const headlinePriceFields = transformEnabled
    ? pageModel.transformModel.headlinePriceFields
    : pageModel.headlinePriceFields;
  const installmentPlans = pageModel.installmentPlans;

  let modeText = pageModel.pricingMode;
  let warningText = pageModel.pricingMode === "Parolu" ? "Parolu Fiyat" : "";
  if (transformEnabled && pageModel.transformModel.type === "normal-to-parolu") {
    modeText = "Parolu Fiyata Donusecek";
    warningText = "Paro Acik";
  } else if (transformEnabled && pageModel.transformModel.type === "parolu-to-normal") {
    modeText = "Normal Fiyata Donusecek";
    warningText = "Paro Bitti";
  }

  return {
    transformEnabled,
    identityFields,
    headlinePriceFields,
    installmentPlans,
    totalFields: identityFields.length + headlinePriceFields.length + installmentPlans.reduce((sum, plan) => sum + plan.fields.length, 0),
    modeText,
    warningText
  };
}

function old_legacy_renderPageModel(pageModel, pageState, rendered) {
  const accordion = document.createElement("details");
  accordion.className = "page-group";
  accordion.open = pageModel.pageNumber === 1;

  const summaryEl = document.createElement("summary");
  summaryEl.className = "page-summary";

  const titleWrap = document.createElement("div");
  titleWrap.className = "page-summary-main";

  const title = document.createElement("span");
  title.className = "page-title";
  title.textContent = pageModel.title;

  const subtitle = document.createElement("span");
  subtitle.className = "page-subtitle";
  subtitle.textContent = `${pageModel.subtitle} • ${rendered.modeText}`;
  titleWrap.append(title, subtitle);

  if (rendered.warningText) {
    const warning = document.createElement("span");
    warning.className = `page-warning ${rendered.transformEnabled ? "page-warning-transform" : "page-warning-parolu"}`;
    warning.textContent = rendered.warningText;
    titleWrap.appendChild(warning);
  }

  const counter = document.createElement("span");
  counter.className = "page-counter";
  counter.textContent = `${rendered.totalFields} alan`;

  summaryEl.append(titleWrap, counter);

  const panel = document.createElement("div");
  panel.className = "page-panel";

  if (pageModel.transformModel.available) {
    panel.appendChild(renderTransformControl(pageModel, pageState));
  }

  if (rendered.identityFields.length) {
    const identityNote = rendered.transformEnabled
      ? "Makine ismi, makine turu, tarih ve uretim yeri donusumle birlikte duzenlenebilir."
      : "Makine ismi, makine turu, tarih ve uretim yeri";
    panel.appendChild(renderFieldSection(pageModel, "Temel Bilgiler", identityNote, rendered.identityFields));
  }

  if (rendered.headlinePriceFields.length) {
    const priceNote = rendered.transformEnabled
      ? pageModel.transformModel.type === "normal-to-parolu"
        ? "Parolu fiyat acildigi icin ek fiyat kutusu gosteriliyor."
        : "Paro bittigi icin sadece normal fiyat tutuluyor."
      : pageModel.pricingMode === "Parolu"
        ? "Tekrarlayan fiyat kutulari yerine ozet alanlar"
        : "Ana fiyat kutulari";
    panel.appendChild(renderFieldSection(pageModel, "Ana Fiyatlar", priceNote, rendered.headlinePriceFields, "price-grid"));
  }

  if (rendered.installmentPlans.length) {
    panel.appendChild(renderPlansSection(pageModel, rendered.installmentPlans));
  }

  accordion.append(summaryEl, panel);
  return accordion;
}

function renderTransformControl(pageModel, pageState) {
  const section = document.createElement("section");
  section.className = "editor-section transform-section";

  const header = document.createElement("div");
  header.className = "section-header";

  const heading = document.createElement("h3");
  heading.textContent = "Sablon Donusumu";

  const note = document.createElement("p");
  note.className = "section-note";
  note.textContent = pageModel.transformModel.note;
  header.append(heading, note);

  const toggle = document.createElement("label");
  toggle.className = "toggle-card";

  const toggleCopy = document.createElement("div");
  toggleCopy.className = "toggle-copy";

  const toggleLabel = document.createElement("strong");
  toggleLabel.textContent = pageModel.transformModel.label;

  const toggleHelp = document.createElement("span");
  toggleHelp.textContent = pageModel.transformModel.helper;
  toggleCopy.append(toggleLabel, toggleHelp);

  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = pageState.transformEnabled;
  input.addEventListener("change", () => {
    pageState.transformEnabled = input.checked;
    renderAnalysis();
  });

  toggle.append(toggleCopy, input);
  section.append(header, toggle);
  return section;
}

function old_legacy_renderFieldSection(pageModel, titleText, noteText, fields, gridClass = "field-grid") {
  const section = document.createElement("section");
  section.className = "editor-section";

  const header = document.createElement("div");
  header.className = "section-header";

  const title = document.createElement("h3");
  title.textContent = titleText;

  const note = document.createElement("p");
  note.className = "section-note";
  note.textContent = noteText;
  header.append(title, note);

  const grid = document.createElement("div");
  grid.className = gridClass;

  for (const field of fields) {
    grid.appendChild(renderFieldCard(pageModel, field));
  }

  section.append(header, grid);
  return section;
}

function renderPlansSection(pageModel, plans) {
  const section = document.createElement("section");
  section.className = "editor-section";

  const header = document.createElement("div");
  header.className = "section-header";

  const heading = document.createElement("h3");
  heading.textContent = "Taksit Gruplari";

  const note = document.createElement("p");
  note.className = "section-note";
  note.textContent = "Pesinat, taksit ve toplam alanlari plan bazli gruplanir.";

  header.append(heading, note);

  const plansWrap = document.createElement("div");
  plansWrap.className = "plan-list";

  for (const plan of plans) {
    const planCard = document.createElement("article");
    planCard.className = "plan-card";

    const planTitle = document.createElement("h4");
    planTitle.textContent = plan.label;

    const planGrid = document.createElement("div");
    planGrid.className = "field-grid plan-grid";

    for (const field of plan.fields) {
      planGrid.appendChild(renderFieldCard(pageModel, field));
    }

    planCard.append(planTitle, planGrid);
    plansWrap.appendChild(planCard);
  }

  section.append(header, plansWrap);
  return section;
}

function old_legacy_renderFieldCard(pageModel, field) {
  const card = document.createElement("article");
  card.className = "field-card";

  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = field.label;

  const current = document.createElement("p");
  current.className = "field-current";
  current.textContent = `Mevcut: ${field.originalValue}`;

  const input = document.createElement("input");
  input.className = "field-input";
  input.type = "text";
  input.value = getFieldValue(pageModel.pageNumber, field);
  input.autocomplete = "off";
  input.spellcheck = false;
  input.addEventListener("input", () => {
    setFieldValue(pageModel.pageNumber, field.key, input.value);
  });

  const hint = document.createElement("p");
  hint.className = "field-hint";
  hint.textContent = field.hint;

  card.append(label, current, input, hint);
  return card;
}

function getAllFields(pageModel) {
  return [
    ...pageModel.identityFields,
    ...pageModel.headlinePriceFields,
    ...pageModel.installmentPlans.flatMap((plan) => plan.fields)
  ];
}

function getFieldValue(pageNumber, field) {
  const state = pageStates.get(pageNumber);
  return state?.values?.[field.key] ?? field.originalValue;
}

function setFieldValue(pageNumber, key, value) {
  const state = pageStates.get(pageNumber);
  if (state) {
    state.values[key] = value;
  }
}

function collectSubmission() {
  const replacements = [];
  const templateTransforms = [];
  const problems = [];
  const seen = new Map();
  let requestedTransformCount = 0;

  for (const pageModel of currentPageModels) {
    const pageState = pageStates.get(pageModel.pageNumber);
    const transformEnabled = Boolean(pageState?.transformEnabled && pageModel.transformModel?.available);

    if (transformEnabled) {
      for (const field of getTransformReplacementFields(pageModel)) {
        const nextValue = normalizeWhitespace(getFieldValue(pageModel.pageNumber, field));
        const currentValue = normalizeWhitespace(field.originalValue);

        if (!nextValue) {
          problems.push(`${pageModel.title} - ${field.label} bos birakilamaz.`);
          continue;
        }

        if (nextValue === currentValue) {
          continue;
        }

        const operations = buildReplacementOperations(field, nextValue);
        if (!operations.length) {
          problems.push(`${pageModel.title} - ${field.label} icin metin parcasi uretilemedi.`);
          continue;
        }

        for (const operation of operations) {
          seen.set(operation.id, operation.replacementText);
        }
      }

      requestedTransformCount += 1;
      const transformPayload = buildTemplateTransformPayload(pageModel, pageState, problems);
      if (transformPayload) {
        templateTransforms.push(transformPayload);
      }
      continue;
    }

    for (const field of getAllFields(pageModel)) {
      const nextValue = normalizeWhitespace(getFieldValue(pageModel.pageNumber, field));
      const currentValue = normalizeWhitespace(field.originalValue);

      if (!nextValue) {
        problems.push(`${pageModel.title} - ${field.label} bos birakilamaz.`);
        continue;
      }

      if (nextValue === currentValue) {
        continue;
      }

      const operations = buildReplacementOperations(field, nextValue);
      if (!operations.length) {
        problems.push(`${pageModel.title} - ${field.label} icin metin parcasi uretilemedi.`);
        continue;
      }

      for (const operation of operations) {
        seen.set(operation.id, operation.replacementText);
      }
    }
  }

  for (const [id, replacementText] of seen.entries()) {
    replacements.push({ id, replacementText });
  }

  if (requestedTransformCount > 0 && !templateTransforms.length && !problems.length) {
    problems.push("Secilen sablon donusumu icin kayit verisi hazirlanamadi. Sayfayi yenileyip PDF'yi yeniden yukleyin.");
  }

  return { replacements, templateTransforms, problems };
}

function getTransformReplacementFields(pageModel) {
  return pageModel.identityFields.filter((field) => field.key === "machine-name" || field.key === "machine-type");
}

function buildTemplateTransformPayload(pageModel, pageState, problems) {
  const machineNameField = pageModel.identityFields.find((field) => field.key === "machine-name");
  const machineTypeField = pageModel.identityFields.find((field) => field.key === "machine-type");
  const mainPriceField = pageModel.transformModel.headlinePriceFields.find((field) => field.key === "main-price") || pageModel.headlinePriceFields.find((field) => field.key === "main-price") || pageModel.headlinePriceFields[0];
  const paroluPriceField = pageModel.transformModel.headlinePriceFields.find((field) => field.key === "parolu-price-virtual");
  const dateField = pageModel.transformModel.dateField;
  const productionField = pageModel.transformModel.productionField;

  const machineName = requiredFieldValue(pageModel, pageState, machineNameField, problems);
  const machineType = requiredFieldValue(pageModel, pageState, machineTypeField, problems);
  const mainPrice = requiredFieldValue(pageModel, pageState, mainPriceField, problems);
  const paroluPrice = pageModel.transformModel.type === "normal-to-parolu"
    ? requiredFieldValue(pageModel, pageState, paroluPriceField, problems)
    : "";
  const date = requiredFieldValue(pageModel, pageState, dateField, problems);
  const productionPlace = requiredFieldValue(pageModel, pageState, productionField, problems);

  const rows = pageModel.installmentPlans.map((plan) => ({
    label: plan.label,
    pesinat: requiredFieldValue(pageModel, pageState, plan.fields[0], problems),
    taksit: requiredFieldValue(pageModel, pageState, plan.fields[1], problems),
    toplam: requiredFieldValue(pageModel, pageState, plan.fields[2], problems)
  }));

  if (problems.length) {
    return null;
  }

  return {
    pageNumber: pageModel.pageNumber,
    type: pageModel.transformModel.type,
    values: {
      machineName,
      machineType,
      mainPrice,
      paroluPrice,
      date,
      productionPlace,
      rows
    }
  };
}

function requiredFieldValue(pageModel, pageState, field, problems) {
  if (!field) {
    return "";
  }
  const value = normalizeWhitespace(pageState.values[field.key] ?? field.originalValue);
  if (!value) {
    problems.push(`${pageModel.title} - ${field.label} bos birakilamaz.`);
  }
  return value;
}

function deriveProductionField(page) {
  const entries = page.entries
    .filter((entry) => entry.bbox && entry.originalText)
    .map((entry) => ({ ...entry, text: normalizeWhitespace(entry.originalText) }))
    .sort((left, right) => (left.bbox?.[1] ?? 0) - (right.bbox?.[1] ?? 0) || (left.bbox?.[0] ?? 0) - (right.bbox?.[0] ?? 0));

  const labelEntry = entries.find((entry) => stripDiacritics(entry.text.toUpperCase()).includes("URETIM YERI"));
  if (!labelEntry) {
    return null;
  }

  const sameLineEntries = entries
    .filter((entry) => Math.abs((entry.bbox?.[1] ?? 0) - (labelEntry.bbox?.[1] ?? 0)) <= 1.5)
    .sort((left, right) => (left.bbox?.[0] ?? 0) - (right.bbox?.[0] ?? 0));

  const valueEntries = [];
  for (const entry of sameLineEntries) {
    if ((entry.bbox?.[0] ?? 0) <= (labelEntry.bbox?.[2] ?? 0)) {
      continue;
    }
    if (!/\p{L}/u.test(entry.text)) {
      continue;
    }
    valueEntries.push({ id: entry.id, originalText: entry.text, prefix: "" });
  }

  return valueEntries.length
    ? {
        key: "production-place",
        label: "Uretim Yeri",
        originalValue: valueEntries.map((segment) => segment.originalText).join(" "),
        hint: "Footer bilgisindeki uretim ulkesi",
        transform: "plain",
        projection: "split",
        prefix: "",
        segments: valueEntries
      }
    : null;
}

function buildVirtualField(key, label, originalValue, hint) {
  return {
    key,
    label,
    originalValue,
    hint,
    transform: "plain",
    projection: "single",
    prefix: "",
    segments: []
  };
}





const renderAnalysis = old_legacy_renderAnalysis;
const buildPageModel = old_legacy_buildPageModel;
const renderPageModel = old_legacy_renderPageModel;
const renderFieldSection = old_legacy_renderFieldSection;
const renderFieldCard = old_legacy_renderFieldCard;



