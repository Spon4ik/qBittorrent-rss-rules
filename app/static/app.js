function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function buildTitleRegexFragment(value) {
  const tokens = (value || "").toLocaleLowerCase().match(/\w+/gu);
  if (!tokens || tokens.length === 0) {
    return escapeRegex((value || "").toLocaleLowerCase().trim());
  }
  return tokens.join("[\\s._-]*");
}

function normalizeReleaseYear(value) {
  const cleaned = (value || "").trim();
  if (!cleaned) {
    return "";
  }
  const match = cleaned.match(/\b(\d{4})\b/u);
  if (match) {
    return match[1];
  }
  return cleaned;
}

function parseAdditionalIncludes(value) {
  const parts = (value || "").split(/[\n,;]+/u);
  const items = [];
  const seen = new Set();

  for (const rawPart of parts) {
    const candidate = rawPart.trim();
    if (!candidate) {
      continue;
    }
    const key = candidate.toLocaleLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    items.push(candidate);
  }

  return items;
}

function parseAdditionalKeywordAlternativeGroups(value) {
  const items = Array.isArray(value)
    ? parseAdditionalIncludes((value || []).join(","))
    : parseAdditionalIncludes(value);
  const groups = [];
  const seenGroups = new Set();

  for (const item of items) {
    const alternatives = [];
    const seenAlternatives = new Set();
    for (const part of String(item || "").split("|")) {
      const candidate = part.trim();
      if (!candidate) {
        continue;
      }
      const key = candidate.toLocaleLowerCase();
      if (seenAlternatives.has(key)) {
        continue;
      }
      seenAlternatives.add(key);
      alternatives.push(candidate);
    }
    if (alternatives.length === 0) {
      continue;
    }
    const groupKey = alternatives.map((entry) => entry.toLocaleLowerCase()).join("||");
    if (seenGroups.has(groupKey)) {
      continue;
    }
    seenGroups.add(groupKey);
    groups.push(alternatives);
  }

  return groups;
}

function looksLikeFullMustContainOverride(value) {
  const candidate = (value || "").trim();
  if (!candidate) {
    return false;
  }
  const fullOverridePrefixes = ["(?i", "(?m", "(?s", "(?x", "(?-", "(?=", "(?!", "(?<=", "(?<!", "(?P"];
  if (fullOverridePrefixes.some((prefix) => candidate.startsWith(prefix))) {
    return true;
  }
  return ["(?=", "(?!", "(?<=", "(?<!"].some((token) => candidate.includes(token));
}

function parseManualMustContainAdditions(value) {
  const parts = (value || "").split(/\r?\n/u);
  const items = [];
  const seen = new Set();

  for (const rawPart of parts) {
    const candidate = rawPart.trim();
    if (!candidate) {
      continue;
    }
    const key = candidate.toLocaleLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    items.push(candidate);
  }

  return items;
}

function buildManualMustContainFragments(value) {
  const regexMetaPattern = /[\\.^$*+?{}\[\]|()]/u;
  return parseManualMustContainAdditions(value).map((item) => {
    if (regexMetaPattern.test(item)) {
      return `(?:${item})`;
    }
    return buildTitleRegexFragment(item);
  });
}

function parseAdditionalIncludeGroups(value) {
  const cleaned = String(value || "").trim();
  if (!cleaned) {
    return [];
  }
  const rawSegments = cleaned.includes("|") ? cleaned.split("|") : [cleaned];
  const groups = [];
  const seen = new Set();
  for (const segment of rawSegments) {
    const terms = parseAdditionalIncludes(segment);
    if (terms.length === 0) {
      continue;
    }
    const key = terms.map((item) => item.toLocaleLowerCase()).join("||");
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    groups.push(terms);
  }
  return groups;
}

function normalizeAdditionalIncludeGroups(value) {
  if (!value) {
    return [];
  }
  if (typeof value === "string") {
    return parseAdditionalIncludeGroups(value);
  }
  if (!Array.isArray(value)) {
    return [];
  }
  const groups = [];
  const seen = new Set();
  for (const item of value) {
    let terms = [];
    if (Array.isArray(item)) {
      terms = parseAdditionalIncludes(item.join(","));
    } else {
      terms = parseAdditionalIncludes(String(item || ""));
    }
    if (terms.length === 0) {
      continue;
    }
    const key = terms.map((term) => term.toLocaleLowerCase()).join("||");
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    groups.push(terms);
  }
  return groups;
}

function parseJsonData(rawValue, fallback) {
  if (!rawValue) {
    return fallback;
  }
  try {
    return JSON.parse(rawValue);
  } catch {
    return fallback;
  }
}

function formatJellyfinEpisodeKey(seasonNumber, episodeNumber) {
  const normalizedSeason = Math.max(0, Math.min(99, Number(seasonNumber) || 0));
  const normalizedEpisode = Math.max(0, Math.min(99, Number(episodeNumber) || 0));
  return `S${String(normalizedSeason).padStart(2, "0")}E${String(normalizedEpisode).padStart(2, "0")}`;
}

function normalizeJellyfinEpisodeKeys(value) {
  const normalized = [];
  const seen = new Set();
  const candidates = Array.isArray(value)
    ? value
    : parseJsonData(String(value || "").trim(), []);
  for (const item of Array.isArray(candidates) ? candidates : []) {
    const match = String(item || "").trim().match(/^s(\d{1,2})e(\d{1,2})$/iu);
    if (!match) {
      continue;
    }
    const episodeKey = formatJellyfinEpisodeKey(match[1], match[2]);
    if (seen.has(episodeKey)) {
      continue;
    }
    seen.add(episodeKey);
    normalized.push(episodeKey);
  }
  return normalized;
}

function buildQualityPatternMap(options) {
  const patternMap = {};
  for (const option of options || []) {
    if (!option?.value || !option?.pattern) {
      continue;
    }
    patternMap[option.value] = option.pattern;
  }
  return patternMap;
}

function buildQualityTokenGroupMapFromElements(container) {
  const tokenGroupMap = {};
  if (!container) {
    return tokenGroupMap;
  }
  for (const tokenItem of container.querySelectorAll("[data-quality-token-item]")) {
    const token = String(tokenItem.dataset.qualityToken || "").trim();
    const groupKey = String(tokenItem.dataset.qualityGroupKey || "").trim();
    if (!token || !groupKey || tokenGroupMap[token]) {
      continue;
    }
    tokenGroupMap[token] = groupKey;
  }
  return tokenGroupMap;
}

function buildFilterProfileMap(profiles) {
  const profileMap = {};
  for (const profile of profiles || []) {
    if (!profile?.key) {
      continue;
    }
    profileMap[profile.key] = profile;
  }
  return profileMap;
}

function normalizeMediaTypes(scope) {
  if (!Array.isArray(scope)) {
    return [];
  }
  return scope.filter((item) => typeof item === "string" && item.trim()).map((item) => item.trim());
}

function mediaTypeMatchesScope(mediaType, scope) {
  if (!mediaType || mediaType === "other") {
    return true;
  }
  const normalizedScope = normalizeMediaTypes(scope);
  if (normalizedScope.length === 0) {
    return true;
  }
  return normalizedScope.includes(mediaType);
}

function getCheckedValues(container, name) {
  return Array.from(container.querySelectorAll(`input[name="${name}"]:checked`)).map((input) => input.value);
}

function setCheckedValues(container, name, values) {
  const selected = new Set(values || []);
  container.querySelectorAll(`input[name="${name}"]`).forEach((input) => {
    input.checked = selected.has(input.value);
  });
}

function orderedValuesMatch(left, right) {
  if ((left || []).length !== (right || []).length) {
    return false;
  }
  return (left || []).every((value, index) => value === (right || [])[index]);
}

function buildQualityRegexGroups(tokens, patternMap, tokenGroupMap = {}) {
  const groups = [];
  const indexByGroupKey = new Map();
  const fallbackGroupKey = "__ungrouped__";

  for (const token of tokens || []) {
    const pattern = patternMap[token];
    if (!pattern) {
      continue;
    }
    const rawGroupKey = tokenGroupMap[token];
    const groupKey = rawGroupKey && String(rawGroupKey).trim()
      ? String(rawGroupKey).trim()
      : fallbackGroupKey;
    let groupIndex = indexByGroupKey.get(groupKey);
    if (groupIndex === undefined) {
      groupIndex = groups.length;
      groups.push({ seenPatterns: new Set(), patterns: [] });
      indexByGroupKey.set(groupKey, groupIndex);
    }
    const group = groups[groupIndex];
    if (group.seenPatterns.has(pattern)) {
      continue;
    }
    group.seenPatterns.add(pattern);
    group.patterns.push(pattern);
  }

  return groups
    .map((group) => group.patterns)
    .filter((patterns) => patterns.length > 0)
    .map((patterns) => `(?:${patterns.join("|")})`);
}

function buildQualityRegex(tokens, patternMap) {
  const patterns = [];
  const seenPatterns = new Set();
  for (const token of tokens || []) {
    const pattern = patternMap[token];
    if (!pattern || seenPatterns.has(pattern)) {
      continue;
    }
    seenPatterns.add(pattern);
    patterns.push(pattern);
  }
  if (patterns.length === 0) {
    return "";
  }
  return `(?:${patterns.join("|")})`;
}

function buildQualityIncludeRegex(tokens, patternMap, tokenGroupMap = {}) {
  const regexGroups = buildQualityRegexGroups(tokens, patternMap, tokenGroupMap);
  if (regexGroups.length === 0) {
    return "";
  }
  if (regexGroups.length === 1) {
    return regexGroups[0];
  }
  return regexGroups.map((group) => `(?=.*${group})`).join("");
}

function normalizeQualityTokenSelection(includeTokens, excludeTokens) {
  const normalizedIncludeTokens = [];
  const includeKeys = new Set();
  for (const token of includeTokens || []) {
    const candidate = String(token || "").trim();
    const key = candidate.toLocaleLowerCase();
    if (!candidate || includeKeys.has(key)) {
      continue;
    }
    includeKeys.add(key);
    normalizedIncludeTokens.push(candidate);
  }

  const normalizedExcludeTokens = [];
  const excludeKeys = new Set();
  for (const token of excludeTokens || []) {
    const candidate = String(token || "").trim();
    const key = candidate.toLocaleLowerCase();
    if (!candidate || includeKeys.has(key) || excludeKeys.has(key)) {
      continue;
    }
    excludeKeys.add(key);
    normalizedExcludeTokens.push(candidate);
  }

  return {
    includeTokens: normalizedIncludeTokens,
    excludeTokens: normalizedExcludeTokens,
  };
}

function bindExclusiveQualitySelections(container, includeName, excludeName, onChange) {
  container.querySelectorAll(`input[name="${includeName}"]`).forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) {
        const opposite = container.querySelector(`input[name="${excludeName}"][value="${input.value}"]`);
        if (opposite) {
          opposite.checked = false;
        }
      }
      onChange?.();
    });
  });

  container.querySelectorAll(`input[name="${excludeName}"]`).forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) {
        const opposite = container.querySelector(`input[name="${includeName}"][value="${input.value}"]`);
        if (opposite) {
          opposite.checked = false;
        }
      }
      onChange?.();
    });
  });
}

const QUALITY_TOKEN_MODES = ["off", "include", "exclude"];

function normalizeQualityTokenMode(value) {
  const normalized = String(value || "off").trim().toLocaleLowerCase();
  return QUALITY_TOKEN_MODES.includes(normalized) ? normalized : "off";
}

function qualityTokenModeIndex(modeValue) {
  return QUALITY_TOKEN_MODES.indexOf(normalizeQualityTokenMode(modeValue));
}

function qualityTokenModeText(modeValue) {
  const mode = normalizeQualityTokenMode(modeValue);
  if (mode === "include") {
    return "Include";
  }
  if (mode === "exclude") {
    return "Exclude";
  }
  return "Off";
}

function readQualityTokenItemElements(tokenItem) {
  return {
    includeStateInput: tokenItem.querySelector('input[data-quality-token-state="include"]'),
    excludeStateInput: tokenItem.querySelector('input[data-quality-token-state="exclude"]'),
    slider: tokenItem.querySelector("[data-quality-token-slider]"),
    sliderControl: tokenItem.querySelector("[data-quality-token-slider-control]"),
  };
}

function setQualityTokenSliderMode(tokenItem, modeValue, disabled = false) {
  const { slider, sliderControl } = readQualityTokenItemElements(tokenItem);
  if (!slider) {
    return;
  }
  const normalizedMode = normalizeQualityTokenMode(modeValue);
  slider.dataset.qualityTokenMode = normalizedMode;
  if (sliderControl) {
    sliderControl.disabled = disabled;
    sliderControl.setAttribute("aria-disabled", disabled ? "true" : "false");
    sliderControl.setAttribute("aria-valuenow", String(qualityTokenModeIndex(normalizedMode)));
    sliderControl.setAttribute("aria-valuetext", qualityTokenModeText(normalizedMode));
  }
}

function syncQualityTokenItemToStateInputs(tokenItem) {
  const {
    includeStateInput,
    excludeStateInput,
    slider,
  } = readQualityTokenItemElements(tokenItem);
  if (!includeStateInput || !excludeStateInput) {
    return;
  }
  const modeValue = normalizeQualityTokenMode(slider?.dataset.qualityTokenMode || "off");
  const disabled = Boolean(includeStateInput.disabled || excludeStateInput.disabled);
  includeStateInput.checked = modeValue === "include";
  excludeStateInput.checked = modeValue === "exclude";
  if (disabled) {
    includeStateInput.checked = false;
    excludeStateInput.checked = false;
  }
}

function syncQualityTokenItemFromStateInputs(tokenItem) {
  const {
    includeStateInput,
    excludeStateInput,
  } = readQualityTokenItemElements(tokenItem);
  if (!includeStateInput || !excludeStateInput) {
    return;
  }
  const disabled = Boolean(includeStateInput.disabled || excludeStateInput.disabled);
  if (disabled) {
    includeStateInput.checked = false;
    excludeStateInput.checked = false;
    setQualityTokenSliderMode(tokenItem, "off", true);
    return;
  }
  if (includeStateInput.checked && excludeStateInput.checked) {
    excludeStateInput.checked = false;
  }
  const includeSelected = Boolean(includeStateInput.checked);
  const excludeSelected = Boolean(excludeStateInput.checked && !includeSelected);
  const modeValue = includeSelected ? "include" : (excludeSelected ? "exclude" : "off");
  setQualityTokenSliderMode(tokenItem, modeValue, false);
}

function qualityTokenModeFromPointer(event, sliderControl) {
  const rect = sliderControl.getBoundingClientRect();
  const width = rect.width || 1;
  const pointerOffset = Math.min(Math.max((event.clientX || 0) - rect.left, 0), width - 1);
  const rawIndex = Math.floor((pointerOffset / width) * QUALITY_TOKEN_MODES.length);
  const clampedIndex = Math.min(Math.max(rawIndex, 0), QUALITY_TOKEN_MODES.length - 1);
  return QUALITY_TOKEN_MODES[clampedIndex] || "off";
}

function qualityTokenStepMode(currentMode, step) {
  const currentIndex = qualityTokenModeIndex(currentMode);
  const safeIndex = currentIndex >= 0 ? currentIndex : 0;
  const nextIndex = (safeIndex + step + QUALITY_TOKEN_MODES.length) % QUALITY_TOKEN_MODES.length;
  return QUALITY_TOKEN_MODES[nextIndex] || "off";
}

function initUnifiedQualityTokenControls(container, { onChange } = {}) {
  const tokenItems = Array.from(container.querySelectorAll("[data-quality-token-item]"));
  if (tokenItems.length === 0) {
    return {
      syncFromStateInputs() {},
    };
  }

  const handleStateChange = (tokenItem) => {
    syncQualityTokenItemToStateInputs(tokenItem);
    onChange?.();
  };

  for (const tokenItem of tokenItems) {
    const { sliderControl, slider } = readQualityTokenItemElements(tokenItem);
    syncQualityTokenItemFromStateInputs(tokenItem);
    if (!sliderControl) {
      continue;
    }
    sliderControl.addEventListener("click", (event) => {
      event.preventDefault();
      if (sliderControl.disabled) {
        return;
      }
      const isKeyboardTriggered = event.detail === 0 || !Number.isFinite(event.clientX);
      const currentMode = normalizeQualityTokenMode(slider?.dataset.qualityTokenMode || "off");
      const selectedMode = isKeyboardTriggered
        ? qualityTokenStepMode(currentMode, 1)
        : qualityTokenModeFromPointer(event, sliderControl);
      setQualityTokenSliderMode(tokenItem, selectedMode, false);
      handleStateChange(tokenItem);
    });
    sliderControl.addEventListener("keydown", (event) => {
      if (sliderControl.disabled) {
        return;
      }
      const currentMode = normalizeQualityTokenMode(slider?.dataset.qualityTokenMode || "off");
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        setQualityTokenSliderMode(tokenItem, qualityTokenStepMode(currentMode, -1), false);
        handleStateChange(tokenItem);
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        setQualityTokenSliderMode(tokenItem, qualityTokenStepMode(currentMode, 1), false);
        handleStateChange(tokenItem);
        return;
      }
      if (event.key === "Home") {
        event.preventDefault();
        setQualityTokenSliderMode(tokenItem, "off", false);
        handleStateChange(tokenItem);
        return;
      }
      if (event.key === "End") {
        event.preventDefault();
        setQualityTokenSliderMode(tokenItem, "exclude", false);
        handleStateChange(tokenItem);
      }
    });
  }

  return {
    syncFromStateInputs({ notify = false } = {}) {
      for (const tokenItem of tokenItems) {
        syncQualityTokenItemFromStateInputs(tokenItem);
      }
      if (notify) {
        onChange?.();
      }
    },
  };
}

function sanitizePath(value) {
  return value.replace(/[<>:"|?*]/g, "_").trim();
}

function deriveTitle(form) {
  const explicit = form.querySelector('input[name="normalized_title"]')?.value.trim();
  const content = form.querySelector('input[name="content_name"]')?.value.trim();
  return explicit || content || "";
}

function deriveCategory(form) {
  const mediaType = form.querySelector('select[name="media_type"]')?.value || "series";
  let template = form.dataset.seriesTemplate || "Series/{title} [imdbid-{imdb_id}]";
  if (mediaType === "movie") {
    template = form.dataset.movieTemplate || "Movies/{title} [imdbid-{imdb_id}]";
  } else if (mediaType === "audiobook") {
    template = "Audiobooks/{title}";
  } else if (mediaType === "music") {
    template = "Music/{title}";
  } else if (mediaType === "other") {
    template = "Other/{title} [imdbid-{imdb_id}]";
  }
  const title = sanitizePath(deriveTitle(form));
  const imdbId = form.querySelector('input[name="imdb_id"]')?.value.trim() || "unknown";
  return template
    .replaceAll("{title}", title)
    .replaceAll("{imdb_id}", imdbId)
    .replaceAll("{media_type}", mediaType);
}

function deriveSavePath(form) {
  const template = form.dataset.savePathTemplate || "";
  if (!template.trim()) {
    return "";
  }
  const title = sanitizePath(deriveTitle(form));
  const mediaType = form.querySelector('select[name="media_type"]')?.value || "series";
  const imdbId = form.querySelector('input[name="imdb_id"]')?.value.trim() || "unknown";
  const category = sanitizePath(deriveCategory(form));
  return template
    .replaceAll("{title}", title)
    .replaceAll("{imdb_id}", imdbId)
    .replaceAll("{media_type}", mediaType)
    .replaceAll("{category}", category);
}

function normalizeBoundedPositiveInt(value, { min = 1, max = 99 } = {}) {
  const cleaned = String(value ?? "").trim();
  if (!cleaned) {
    return null;
  }
  const numeric = Number(cleaned);
  if (!Number.isFinite(numeric)) {
    return null;
  }
  const normalized = Math.floor(numeric);
  if (normalized < min || normalized > max) {
    return null;
  }
  return normalized;
}

function buildMinNumericPattern1To99(value) {
  const boundedValue = Math.min(99, Math.max(1, Number(value) || 1));
  if (boundedValue === 99) {
    return "0*99";
  }
  if (boundedValue <= 9) {
    return `(?:0*[${boundedValue}-9]|0*[1-9]\\d)`;
  }
  const tens = Math.floor(boundedValue / 10);
  const ones = boundedValue % 10;
  const parts = [];
  if (ones === 0) {
    parts.push(`0*${tens}\\d`);
  } else if (ones === 9) {
    parts.push(`0*${tens}9`);
  } else {
    parts.push(`0*${tens}[${ones}-9]`);
  }
  if (tens < 9) {
    parts.push(`0*[${tens + 1}-9]\\d`);
  }
  if (parts.length === 1) {
    return parts[0];
  }
  return `(?:${parts.join("|")})`;
}

function buildMinNumericPattern0To99(value) {
  const boundedValue = Math.min(99, Math.max(0, Number(value) || 0));
  if (boundedValue <= 0) {
    return "0*\\d{1,2}";
  }
  return buildMinNumericPattern1To99(boundedValue);
}

function buildEpisodeProgressRegexFragment(startSeasonValue, startEpisodeValue) {
  const startSeason = normalizeBoundedPositiveInt(startSeasonValue, { min: 1, max: 99 });
  const startEpisode = normalizeBoundedPositiveInt(startEpisodeValue, { min: 0, max: 99 });
  if (startSeason === null || startEpisode === null) {
    return "";
  }
  const separators = "[\\s._-]*";
  const seasonExact = `0*${startSeason}`;
  const episodeAny = "0*\\d{1,2}";
  const episodeRangeAny = "0*\\d{1,2}";
  const episodeGe = buildMinNumericPattern0To99(startEpisode);
  const seasonPrefix = "(?:s(?:eason)?[\\s._:-]*)";
  const episodePrefix = "(?:e(?:p(?:isode)?)?[\\s._:-]*)";
  const fragments = [
    `${seasonPrefix}${seasonExact}(?!\\d)${separators}${episodePrefix}${episodeGe}`,
    `${seasonPrefix}${seasonExact}(?!\\d)${separators}${episodePrefix}${episodeRangeAny}${separators}-${separators}(?:${episodePrefix})?${episodeGe}`,
    `${seasonPrefix}${seasonExact}(?!\\d)(?:\\b|$)`,
  ];
  if (startSeason < 99) {
    const seasonAfter = buildMinNumericPattern1To99(startSeason + 1);
    fragments.unshift(`${seasonPrefix}${seasonAfter}(?!\\d)${separators}${episodePrefix}${episodeAny}`);
    fragments.splice(1, 0, `${seasonPrefix}${seasonAfter}(?!\\d)(?:\\b|$)`);
  }
  return `(?:${fragments.join("|")})`;
}

function buildSpecificEpisodeRegexFragment(seasonValue, episodeValue) {
  const seasonNumber = normalizeBoundedPositiveInt(seasonValue, { min: 0, max: 99 });
  const episodeNumber = normalizeBoundedPositiveInt(episodeValue, { min: 0, max: 99 });
  if (seasonNumber === null || episodeNumber === null) {
    return "";
  }
  const separators = "[\\s._-]*";
  const seasonExact = `0*${seasonNumber}`;
  const episodeExact = `0*${episodeNumber}`;
  const episodeRangeAny = "0*\\d{1,2}";
  const seasonPrefix = "(?:s(?:eason)?[\\s._:-]*)";
  const episodePrefix = "(?:e(?:p(?:isode)?)?[\\s._:-]*)";
  const fragments = [
    `${seasonPrefix}${seasonExact}(?!\\d)${separators}${episodePrefix}${episodeExact}(?!\\d)`,
    `${seasonPrefix}${seasonExact}(?!\\d)${separators}${episodePrefix}${episodeRangeAny}${separators}-${separators}(?:${episodePrefix})?${episodeExact}(?!\\d)`,
    `${seasonPrefix}${seasonExact}(?!\\d)${separators}${episodePrefix}${episodeExact}(?!\\d)${separators}-${separators}(?:${episodePrefix})?${episodeRangeAny}`,
  ];
  return `(?:${fragments.join("|")})`;
}

function buildBelowFloorEpisodeRegexFragment(seasonValue, episodeValue) {
  const seasonNumber = normalizeBoundedPositiveInt(seasonValue, { min: 1, max: 99 });
  const episodeNumber = normalizeBoundedPositiveInt(episodeValue, { min: 0, max: 99 });
  if (seasonNumber === null || episodeNumber === null) {
    return "";
  }
  const separators = "[\\s._-]*";
  const seasonExact = `0*${seasonNumber}`;
  const episodeExact = `0*${episodeNumber}`;
  const episodeRangeAny = "0*\\d{1,2}";
  const seasonPrefix = "(?:s(?:eason)?[\\s._:-]*)";
  const episodePrefix = "(?:e(?:p(?:isode)?)?[\\s._:-]*)";
  const fragments = [
    `${seasonPrefix}${seasonExact}(?!\\d)${separators}${episodePrefix}${episodeExact}(?!\\d)(?!${separators}-)`,
    `${seasonPrefix}${seasonExact}(?!\\d)${separators}${episodePrefix}${episodeRangeAny}${separators}-${separators}(?:(?:${episodePrefix}))?${episodeExact}(?!\\d)`,
  ];
  return `(?:${fragments.join("|")})`;
}

function buildLowerEpisodeExclusionRegexFragment(startSeasonValue, startEpisodeValue) {
  const startSeason = normalizeBoundedPositiveInt(startSeasonValue, { min: 1, max: 99 });
  const startEpisode = normalizeBoundedPositiveInt(startEpisodeValue, { min: 0, max: 99 });
  if (startSeason === null || startEpisode === null || startEpisode <= 0) {
    return "";
  }
  const fragments = [];
  for (let episodeNumber = 0; episodeNumber < startEpisode; episodeNumber += 1) {
    const fragment = buildBelowFloorEpisodeRegexFragment(startSeason, episodeNumber);
    if (fragment) {
      fragments.push(fragment);
    }
  }
  if (fragments.length === 0) {
    return "";
  }
  return `(?:${fragments.join("|")})`;
}

function buildExistingEpisodeExclusionRegexFragment(existingEpisodeKeys) {
  const fragments = [];
  for (const episodeKey of normalizeJellyfinEpisodeKeys(existingEpisodeKeys)) {
    const match = episodeKey.match(/^s(\d{1,2})e(\d{1,2})$/iu);
    if (!match) {
      continue;
    }
    const fragment = buildSpecificEpisodeRegexFragment(match[1], match[2]);
    if (fragment) {
      fragments.push(fragment);
    }
  }
  if (fragments.length === 0) {
    return "";
  }
  return `(?:${fragments.join("|")})`;
}

function anchorGeneratedPatternAtStart(pattern) {
  const cleaned = String(pattern || "").trim();
  if (!cleaned) {
    return "";
  }
  if (cleaned.startsWith("(?i)^") || cleaned.startsWith("^")) {
    return cleaned;
  }
  if (cleaned.startsWith("(?i)")) {
    return `(?i)^${cleaned.slice(4)}`;
  }
  return `^${cleaned}`;
}

function deriveGeneratedPattern({
  title,
  useRegex = false,
  includeReleaseYear = false,
  releaseYear = "",
  additionalIncludes = "",
  additionalExcludes = "",
  manualMustContain = "",
  additionalIncludeGroups = [],
  manualMustContainFragments = [],
  qualityIncludeTokens = [],
  qualityExcludeTokens = [],
  qualityPatternMap = {},
  qualityTokenGroupMap = {},
  startSeason = "",
  startEpisode = "",
  jellyfinSearchExistingUnseen = false,
  jellyfinExistingEpisodeNumbers = [],
}) {
  const manualMustContainValue = String(manualMustContain || "").trim();
  const fullManualOverride = looksLikeFullMustContainOverride(manualMustContainValue);
  if (fullManualOverride) {
    return manualMustContainValue;
  }

  const normalizedSelection = normalizeQualityTokenSelection(
    qualityIncludeTokens,
    qualityExcludeTokens
  );
  const qualityIncludeGroups = buildQualityRegexGroups(
    normalizedSelection.includeTokens,
    qualityPatternMap,
    qualityTokenGroupMap
  );
  const qualityExclude = buildQualityRegex(normalizedSelection.excludeTokens, qualityPatternMap);
  const includeKeywordGroups = parseAdditionalKeywordAlternativeGroups(additionalIncludes);
  const excludeKeywordGroups = parseAdditionalKeywordAlternativeGroups(additionalExcludes);
  const includeGroupFragments = buildOptionalKeywordGroupRegexFragments(
    normalizeAdditionalIncludeGroups(additionalIncludeGroups)
  );
  const manualFragments = [
    ...buildManualMustContainFragments(manualMustContainValue),
    ...includeGroupFragments,
    ...((manualMustContainFragments || [])
      .map((item) => String(item || "").trim())
      .filter(Boolean)),
  ];
  const episodeProgressFragment = buildEpisodeProgressRegexFragment(startSeason, startEpisode);
  const lowerEpisodeExclusion = buildLowerEpisodeExclusionRegexFragment(startSeason, startEpisode);
  const jellyfinExistingEpisodeExclusion = jellyfinSearchExistingUnseen
    ? ""
    : buildExistingEpisodeExclusionRegexFragment(jellyfinExistingEpisodeNumbers);
  const normalizedTitle = String(title || "").trim();
  const titleFragment = normalizedTitle ? buildTitleRegexFragment(normalizedTitle) : "";
  const normalizedYear = normalizeReleaseYear(releaseYear);

  const hasGeneratedConditions = Boolean(
    (includeReleaseYear && normalizedYear)
      || includeKeywordGroups.length
      || excludeKeywordGroups.length
      || manualFragments.length
      || qualityIncludeGroups.length > 0
      || qualityExclude
      || episodeProgressFragment
      || lowerEpisodeExclusion
      || jellyfinExistingEpisodeExclusion
  );
  if (!useRegex && !hasGeneratedConditions) {
    return normalizedTitle;
  }

  const positiveFragments = [];
  if (titleFragment) {
    positiveFragments.push(titleFragment);
  }
  if (includeReleaseYear && normalizedYear) {
    positiveFragments.push(escapeRegex(normalizedYear));
  }
  for (const fragment of buildOptionalKeywordGroupRegexFragments(includeKeywordGroups)) {
    positiveFragments.push(fragment);
  }
  if (episodeProgressFragment) {
    positiveFragments.push(episodeProgressFragment);
  }
  for (const fragment of qualityIncludeGroups) {
    positiveFragments.push(fragment);
  }
  for (const fragment of manualFragments) {
    positiveFragments.push(fragment);
  }

  const negativeFragments = [];
  if (qualityExclude) {
    negativeFragments.push(qualityExclude);
  }
  if (lowerEpisodeExclusion) {
    negativeFragments.push(lowerEpisodeExclusion);
  }
  if (jellyfinExistingEpisodeExclusion) {
    negativeFragments.push(jellyfinExistingEpisodeExclusion);
  }
  for (const fragment of buildOptionalKeywordGroupRegexFragments(excludeKeywordGroups)) {
    negativeFragments.push(fragment);
  }

  let pattern = "(?i)";
  for (const fragment of positiveFragments) {
    if (!fragment) {
      continue;
    }
    pattern += `(?=.*${fragment})`;
  }
  for (const fragment of negativeFragments) {
    if (!fragment) {
      continue;
    }
    pattern += `(?!.*${fragment})`;
  }

  if (pattern === "(?i)" && !normalizedTitle) {
    return "";
  }
  return pattern;
}

function buildOptionalKeywordGroupRegexFragments(keywordGroups) {
  const fragments = [];
  for (const group of keywordGroups || []) {
    const groupFragments = group
      .map((item) => buildTitleRegexFragment(item))
      .filter(Boolean);
    if (groupFragments.length === 0) {
      continue;
    }
    if (groupFragments.length === 1) {
      fragments.push(groupFragments[0]);
      continue;
    }
    fragments.push(`(?:${groupFragments.join("|")})`);
  }
  return fragments;
}

function derivePattern(form, qualityPatternMap, qualityTokenGroupMap = {}) {
  const manualMustContain = form.querySelector('textarea[name="must_contain_override"]')?.value.trim();
  if (looksLikeFullMustContainOverride(manualMustContain)) {
    return manualMustContain;
  }
  const jellyfinExistingEpisodeNumbers = normalizeJellyfinEpisodeKeys(
    parseJsonData(form.dataset.jellyfinExistingEpisodeNumbers || "[]", [])
  );
  return deriveGeneratedPattern({
    title: deriveTitle(form),
    useRegex: Boolean(form.querySelector('input[name="use_regex"]')?.checked),
    includeReleaseYear: Boolean(
      form.querySelector('input[type="checkbox"][name="include_release_year"]')?.checked
    ),
    releaseYear: form.querySelector('input[name="release_year"]')?.value || "",
    additionalIncludes: form.querySelector('textarea[name="additional_includes"]')?.value || "",
    additionalExcludes: form.querySelector('textarea[name="must_not_contain"]')?.value || "",
    manualMustContain,
    startSeason: form.querySelector('input[name="start_season"]')?.value || "",
    startEpisode: form.querySelector('input[name="start_episode"]')?.value || "",
    jellyfinSearchExistingUnseen: Boolean(
      form.querySelector('input[name="jellyfin_search_existing_unseen"]')?.checked
    ),
    jellyfinExistingEpisodeNumbers,
    qualityIncludeTokens: getCheckedValues(form, "quality_include_tokens"),
    qualityExcludeTokens: getCheckedValues(form, "quality_exclude_tokens"),
    qualityPatternMap,
    qualityTokenGroupMap,
  });
}

const SEARCH_WORD_CHAR_RE = (() => {
  try {
    return new RegExp("[\\p{L}\\p{N}]", "u");
  } catch {
    return /[a-z0-9]/u;
  }
})();

function normalizeSearchText(value) {
  const lowered = String(value || "").toLocaleLowerCase();
  let normalized = "";
  for (const char of lowered) {
    normalized += SEARCH_WORD_CHAR_RE.test(char) ? char : " ";
  }
  return normalized.replace(/\s+/gu, " ").trim();
}

function parseSearchFilterList(value) {
  const parts = String(value || "").split(/[\n,;]+/u);
  const items = [];
  const seen = new Set();
  for (const rawPart of parts) {
    const candidate = rawPart.trim();
    if (!candidate) {
      continue;
    }
    const key = candidate.toLocaleLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    items.push(candidate);
  }
  return items;
}

const FEED_INDEXER_PATH_RE = /\/api\/v2\.0\/indexers\/([^/]+)\/results\/torznab(?:\/api)?\/?$/iu;
const INDEXER_KEY_STRIP_RE = /[^a-z0-9]+/gu;

function feedUrlToIndexerSlug(feedUrl) {
  const cleaned = String(feedUrl || "").trim();
  if (!cleaned) {
    return "";
  }
  let pathname = "";
  try {
    pathname = new URL(cleaned, window.location.origin).pathname || "";
  } catch {
    pathname = cleaned.split("?")[0] || "";
  }
  const match = pathname.match(FEED_INDEXER_PATH_RE);
  if (!match) {
    return "";
  }
  let decoded = "";
  try {
    decoded = decodeURIComponent(match[1] || "");
  } catch {
    decoded = match[1] || "";
  }
  const slug = decoded.trim().toLocaleLowerCase();
  if (!slug || slug === "all") {
    return "";
  }
  return slug;
}

function buildIndexerKeyVariants(value) {
  const raw = String(value || "").trim().toLocaleLowerCase();
  if (!raw) {
    return [];
  }
  const cleaned = raw.startsWith("www.") ? raw.slice(4) : raw;
  const variants = [];
  const seen = new Set();
  const pushUnique = (candidate) => {
    const normalized = String(candidate || "").trim();
    if (!normalized || seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    variants.push(normalized);
  };
  pushUnique(cleaned);
  pushUnique(cleaned.replace(INDEXER_KEY_STRIP_RE, ""));
  if (cleaned.includes(".")) {
    const hostWithoutTld = cleaned.slice(0, cleaned.lastIndexOf(".")).trim();
    pushUnique(hostWithoutTld);
    pushUnique(hostWithoutTld.replace(INDEXER_KEY_STRIP_RE, ""));
  }
  return variants;
}

function mergeUniqueIndexerVariantKeys(values) {
  const merged = [];
  const seen = new Set();
  for (const value of values || []) {
    for (const variant of buildIndexerKeyVariants(value)) {
      if (seen.has(variant)) {
        continue;
      }
      seen.add(variant);
      merged.push(variant);
    }
  }
  return merged;
}

function normalizeCategoryFilterValue(value) {
  return normalizeSearchText(value || "");
}

function parseSearchAnyKeywordGroups(value) {
  const cleaned = String(value || "").trim();
  if (!cleaned) {
    return [];
  }
  const groupSegments = cleaned.includes("|") ? cleaned.split("|") : [cleaned];
  const groups = [];
  for (const segment of groupSegments) {
    const terms = parseSearchFilterList(segment);
    if (terms.length > 0) {
      groups.push(terms);
    }
  }
  return groups;
}

function parseSearchMb(value) {
  const cleaned = String(value || "").trim();
  if (!cleaned) {
    return null;
  }
  const numeric = Number(cleaned);
  if (!Number.isFinite(numeric) || numeric < 0) {
    return null;
  }
  return numeric;
}

function normalizeSearchImdbId(value) {
  const cleaned = String(value || "").trim().toLocaleLowerCase();
  if (!cleaned) {
    return "";
  }
  if (/^\d+$/u.test(cleaned)) {
    return `tt${cleaned}`;
  }
  if (/^tt\d+$/u.test(cleaned)) {
    return cleaned;
  }
  return "";
}

function initSearchPage(container) {
  const form = container.querySelector("[data-search-form]");
  if (!form) {
    return;
  }

  const queryInput = form.querySelector('input[name="query"]')
    || form.querySelector('input[name="normalized_title"]')
    || form.querySelector('input[name="content_name"]');
  const mediaTypeInput = form.querySelector('select[name="media_type"]');
  const imdbIdInput = form.querySelector('input[name="imdb_id"]');
  const includeReleaseYearInput = form.querySelector('input[type="checkbox"][name="include_release_year"]');
  const releaseYearInput = form.querySelector('input[name="release_year"]');
  const keywordsAllInput = form.querySelector('textarea[name="additional_includes"], input[name="keywords_all"]');
  const keywordsAnyInput = form.querySelector('input[name="keywords_any"]');
  const keywordsNotInput = form.querySelector('textarea[name="must_not_contain"], input[name="keywords_not"]');
  const mustContainOverrideInput = form.querySelector('textarea[name="must_contain_override"]');
  const searchPatternPreview = form.querySelector("#search-pattern-preview");
  const generatedPatternInput = form.querySelector("#search-pattern-preview, #pattern-preview");
  const sizeMinInput = form.querySelector('input[name="size_min_mb"]');
  const sizeMaxInput = form.querySelector('input[name="size_max_mb"]');
  const startSeasonInput = form.querySelector('input[name="start_season"]');
  const startEpisodeInput = form.querySelector('input[name="start_episode"]');
  const filterIndexersInput = container.querySelector('input[name="filter_indexers"]');
  const filterCategoryIdsInput = container.querySelector('input[name="filter_category_ids"]');
  const indexerMultiSelectOptions = container.querySelector('[data-search-multiselect-options="indexers"]');
  const indexerMultiSelectSummary = container.querySelector('[data-search-multiselect-summary="indexers"]');
  const indexerMultiSelectSelectAll = container.querySelector('[data-search-multiselect-select-all="indexers"]');
  const indexerMultiSelectClear = container.querySelector('[data-search-multiselect-clear="indexers"]');
  const categoryMultiSelectOptions = container.querySelector('[data-search-multiselect-options="categories"]');
  const categoryMultiSelectSummary = container.querySelector('[data-search-multiselect-summary="categories"]');
  const categoryMultiSelectSelectAll = container.querySelector('[data-search-multiselect-select-all="categories"]');
  const categoryMultiSelectClear = container.querySelector('[data-search-multiselect-clear="categories"]');
  const categoryScopeStatusElement = container.querySelector("[data-search-category-scope-status]");
  const getFeedUrlInputs = () => Array.from(form.querySelectorAll('input[name="feed_urls"]'));
  const hasFeedSelectionConstraint = () => getFeedUrlInputs().length > 0;
  const getSelectedFeedIndexerSlugs = () => {
    const selected = [];
    const seen = new Set();
    for (const input of getFeedUrlInputs()) {
      if (!input.checked) {
        continue;
      }
      const slug = feedUrlToIndexerSlug(input.value);
      if (!slug || seen.has(slug)) {
        continue;
      }
      seen.add(slug);
      selected.push(slug);
    }
    return selected;
  };
  const qualitySearchTermMap = parseJsonData(container.dataset.qualitySearchTerms || "{}", {});
  const qualityPatternMap = parseJsonData(container.dataset.qualityPatternMap || "{}", {});
  const qualityTokenGroupMap = buildQualityTokenGroupMapFromElements(form);
  const sortHeaderButtons = Array.from(container.querySelectorAll("[data-search-table-sort-field]"));
  const controlSets = Array.from(container.querySelectorAll("[data-search-controls]")).map((controlContainer) => ({
    controlContainer,
    viewModeSelect: controlContainer.querySelector("[data-search-view-mode]"),
    showHiddenToggle: controlContainer.querySelector("[data-search-show-hidden-toggle]"),
    saveDefaultsButton: controlContainer.querySelector("[data-search-save-defaults]"),
    saveDefaultsStatus: controlContainer.querySelector("[data-search-default-status]"),
    clearFiltersButton: controlContainer.querySelector("[data-search-clear-filters]"),
    activeFiltersContainer: controlContainer.querySelector("[data-search-active-filters]"),
    activeFilterList: controlContainer.querySelector("[data-search-active-filter-list]"),
  }));
  const saveDefaultsButtons = controlSets.map((set) => set.saveDefaultsButton).filter(Boolean);
  const saveDefaultsStatuses = controlSets.map((set) => set.saveDefaultsStatus).filter(Boolean);
  const getSearchQueryLabel = () => String(queryInput?.value || container.dataset.searchQuery || "").trim();
  const getSearchQuery = () => normalizeSearchText(getSearchQueryLabel());
  const getSearchImdbId = () => normalizeSearchImdbId(imdbIdInput?.value || "");
  const getJellyfinExistingEpisodeNumbers = () => normalizeJellyfinEpisodeKeys(
    parseJsonData(form.dataset.jellyfinExistingEpisodeNumbers || "[]", [])
  );
  const getJellyfinSearchExistingUnseen = () => Boolean(
    form.querySelector('input[name="jellyfin_search_existing_unseen"]')?.checked
  );
  const DEFAULT_SORT_FIELD = "published_at";
  const DEFAULT_SORT_DIRECTION_BY_FIELD = {
    published_at: "desc",
    seeders: "desc",
    peers: "desc",
    leechers: "desc",
    grabs: "desc",
    size_bytes: "desc",
    year: "desc",
    indexer: "asc",
    title: "asc",
  };
  const SORT_FIELDS = new Set([
    "published_at",
    "seeders",
    "peers",
    "leechers",
    "grabs",
    "size_bytes",
    "year",
    "indexer",
    "title",
  ]);
  const normalizeSortDirection = (value) => (String(value || "").trim().toLocaleLowerCase() === "desc"
    ? "desc"
    : "asc");
  const normalizeSortField = (value) => {
    const cleaned = String(value || "").trim();
    return SORT_FIELDS.has(cleaned) ? cleaned : "";
  };
  const defaultSortDirectionForField = (field) => (
    DEFAULT_SORT_DIRECTION_BY_FIELD[normalizeSortField(field)] || "asc"
  );
  const toggleSortDirection = (direction) => (normalizeSortDirection(direction) === "asc" ? "desc" : "asc");
  const normalizeSortCriteria = (rawValue) => {
    const normalized = [];
    const seen = new Set();
    for (const item of Array.isArray(rawValue) ? rawValue : []) {
      const field = normalizeSortField(item?.field);
      if (!field || seen.has(field)) {
        continue;
      }
      normalized.push({ field, direction: normalizeSortDirection(item?.direction) });
      seen.add(field);
      if (normalized.length >= 3) {
        break;
      }
    }
    if (normalized.length > 0) {
      return normalized;
    }
    return [{ field: DEFAULT_SORT_FIELD, direction: "desc" }];
  };
  const normalizeViewMode = () => "table";
  let controlState = {
    viewMode: normalizeViewMode(container.dataset.defaultViewMode || "table"),
    sortCriteria: normalizeSortCriteria(parseJsonData(container.dataset.defaultSort || "", [])),
    showHiddenRows: false,
  };

  const parseOptionalNumber = (value) => {
    const cleaned = String(value ?? "").trim();
    if (!cleaned) {
      return null;
    }
    const numeric = Number(cleaned);
    if (!Number.isFinite(numeric)) {
      return null;
    }
    return numeric;
  };

  const parseIsoDateMs = (value) => {
    const cleaned = String(value || "").trim();
    if (!cleaned) {
      return null;
    }
    const timestamp = Date.parse(cleaned);
    if (!Number.isFinite(timestamp)) {
      return null;
    }
    return timestamp;
  };

  const mergeUniqueTerms = (...termLists) => {
    const merged = [];
    const seen = new Set();
    for (const termList of termLists) {
      for (const rawTerm of termList || []) {
        const candidate = String(rawTerm || "").trim();
        if (!candidate) {
          continue;
        }
        const key = candidate.toLocaleLowerCase();
        if (seen.has(key)) {
          continue;
        }
        seen.add(key);
        merged.push(candidate);
      }
    }
    return merged;
  };

  const qualitySearchTermsForTokens = (tokens) => {
    const termLists = [];
    for (const token of tokens || []) {
      const candidate = String(token || "").trim();
      if (!candidate) {
        continue;
      }
      const mappedTerms = qualitySearchTermMap[candidate];
      if (Array.isArray(mappedTerms) && mappedTerms.length > 0) {
        termLists.push(
          mappedTerms
            .map((item) => String(item || "").trim())
            .filter((item) => item.length > 0)
        );
        continue;
      }
      termLists.push([candidate]);
    }
    return mergeUniqueTerms(...termLists);
  };

  const resolveSearchTokenKeywordState = () => {
    const normalizedSelection = normalizeQualityTokenSelection(
      mergeUniqueTerms(getCheckedValues(form, "quality_include_tokens")),
      mergeUniqueTerms(getCheckedValues(form, "quality_exclude_tokens"))
    );
    const includeKeywordTokens = normalizedSelection.includeTokens;
    const excludeKeywordTokens = normalizedSelection.excludeTokens;
    const includeKeywordPattern = buildQualityIncludeRegex(
      includeKeywordTokens,
      qualityPatternMap,
      qualityTokenGroupMap
    );
    const excludeKeywordPattern = buildQualityRegex(excludeKeywordTokens, qualityPatternMap);
    const includeKeywordRegex = compileQualityRegex(includeKeywordPattern);
    const excludeKeywordRegex = compileQualityRegex(excludeKeywordPattern);
    const includeKeywordResolvedTerms = qualitySearchTermsForTokens(includeKeywordTokens);
    const includeKeywordTerms = includeKeywordRegex ? [] : includeKeywordResolvedTerms;
    const excludeKeywordTerms = excludeKeywordRegex ? [] : qualitySearchTermsForTokens(excludeKeywordTokens);
    const includeKeywordConflictKeys = new Set(
      includeKeywordResolvedTerms
        .map((item) => normalizeSearchText(item))
        .filter(Boolean)
    );
    const manualKeywordsNot = mergeUniqueTerms(
      ...parseAdditionalKeywordAlternativeGroups(keywordsNotInput?.value || "")
    ).filter(
      (item) => !includeKeywordConflictKeys.has(normalizeSearchText(item))
    );
    return {
      includeKeywordTokens,
      excludeKeywordTokens,
      includeKeywordRegex,
      excludeKeywordRegex,
      includeKeywordTerms,
      excludeKeywordTerms,
      manualKeywordsNot,
    };
  };

  const compileQualityRegex = (pattern) => {
    const cleaned = String(pattern || "").trim();
    if (!cleaned) {
      return null;
    }
    try {
      return new RegExp(cleaned, "iu");
    } catch {
      return null;
    }
  };

  const compileGeneratedPatternRegex = (pattern) => {
    const cleaned = String(pattern || "").trim();
    if (!cleaned) {
      return null;
    }
    let source = cleaned;
    let flags = "u";
    if (source.startsWith("(?i)")) {
      source = source.slice(4);
      flags = "iu";
    }
    try {
      return new RegExp(source, flags);
    } catch {
      try {
        return new RegExp(escapeRegex(source), "iu");
      } catch {
        return null;
      }
    }
  };

  const cloneFilters = (filters) => ({
    query: filters.query,
    imdbId: filters.imdbId,
    releaseYear: filters.releaseYear,
    keywordsAll: [...filters.keywordsAll],
    keywordsAnyGroups: filters.keywordsAnyGroups.map((group) => [...group]),
    keywordsNot: [...filters.keywordsNot],
    qualityIncludeTokens: [...(filters.qualityIncludeTokens || [])],
    qualityExcludeTokens: [...(filters.qualityExcludeTokens || [])],
    qualityIncludeRegex: filters.qualityIncludeRegex || null,
    qualityExcludeRegex: filters.qualityExcludeRegex || null,
    generatedPatternRegex: filters.generatedPatternRegex || null,
    manualMustContain: String(filters.manualMustContain || ""),
    startSeason: filters.startSeason,
    startEpisode: filters.startEpisode,
    sizeMinMb: filters.sizeMinMb,
    sizeMaxMb: filters.sizeMaxMb,
    feedScopeBlocksAll: Boolean(filters.feedScopeBlocksAll),
    feedScopedIndexers: [...(filters.feedScopedIndexers || [])],
    feedScopedIndexerVariantKeys: [...(filters.feedScopedIndexerVariantKeys || [])],
    explicitIndexers: [...(filters.explicitIndexers || [])],
    indexers: [...filters.indexers],
    indexerVariantKeys: [...(filters.indexerVariantKeys || [])],
    categories: [...filters.categories],
  });

  const NUMERIC_SORT_FIELDS = new Set([
    "published_at",
    "seeders",
    "peers",
    "leechers",
    "grabs",
    "size_bytes",
    "year",
  ]);

  const sortGlyphForDirection = (field, direction) => {
    const normalizedField = normalizeSortField(field);
    const normalizedDirection = normalizeSortDirection(direction);
    const numeric = NUMERIC_SORT_FIELDS.has(normalizedField);
    if (numeric) {
      return normalizedDirection === "asc" ? "0-9" : "9-0";
    }
    return normalizedDirection === "asc" ? "A-Z" : "Z-A";
  };

  const renderSortHeaders = () => {
    const activeByField = new Map(
      controlState.sortCriteria.map((criterion, index) => [criterion.field, { ...criterion, level: index + 1 }])
    );
    for (const button of sortHeaderButtons) {
      const field = normalizeSortField(button.dataset.searchTableSortField || "");
      if (!field) {
        continue;
      }
      const active = activeByField.get(field);
      const th = button.closest("th");
      const glyph = button.querySelector(`[data-search-sort-glyph="${field}"]`)
        || button.querySelector("[data-search-sort-glyph]");
      if (!active) {
        button.dataset.sortActive = "0";
        button.setAttribute("aria-pressed", "false");
        button.setAttribute("title", "Click to sort ascending. Shift+click adds to multi-sort.");
        if (glyph) {
          glyph.textContent = "↕";
        }
        if (th) {
          th.setAttribute("aria-sort", "none");
        }
        continue;
      }

      button.dataset.sortActive = "1";
      button.setAttribute("aria-pressed", "true");
      button.setAttribute(
        "title",
        `Sorted ${active.direction} at level ${active.level}. `
        + "Click to toggle direction. Shift+click keeps other sort levels."
      );
      if (glyph) {
        const label = sortGlyphForDirection(field, active.direction);
        glyph.textContent = controlState.sortCriteria.length > 1 ? `${label}${active.level}` : label;
      }
      if (th) {
        if (active.level === 1) {
          th.setAttribute("aria-sort", active.direction === "desc" ? "descending" : "ascending");
        } else {
          th.setAttribute("aria-sort", "none");
        }
      }
    }
  };

  const writeControlStateToSet = (controlSet, state) => {
    if (controlSet.viewModeSelect) {
      controlSet.viewModeSelect.value = state.viewMode;
    }
    if (controlSet.showHiddenToggle) {
      controlSet.showHiddenToggle.checked = Boolean(state.showHiddenRows);
    }
  };

  const updateSortFromHeader = (field, additive = false) => {
    const normalizedField = normalizeSortField(field);
    if (!normalizedField) {
      return;
    }

    const current = controlState.sortCriteria.map((criterion) => ({ ...criterion }));
    const existingIndex = current.findIndex((criterion) => criterion.field === normalizedField);
    let nextCriteria = [];

    if (additive) {
      if (existingIndex >= 0) {
        const existing = current.splice(existingIndex, 1)[0];
        existing.direction = toggleSortDirection(existing.direction);
        nextCriteria = [existing, ...current];
      } else {
        nextCriteria = [
          { field: normalizedField, direction: defaultSortDirectionForField(normalizedField) },
          ...current,
        ];
      }
    } else if (existingIndex === 0) {
      nextCriteria = [
        {
          field: normalizedField,
          direction: toggleSortDirection(current[0].direction),
        }
      ];
    } else if (existingIndex > 0) {
      nextCriteria = [{ ...current[existingIndex] }];
    } else {
      nextCriteria = [{ field: normalizedField, direction: defaultSortDirectionForField(normalizedField) }];
    }

    controlState = {
      ...controlState,
      sortCriteria: normalizeSortCriteria(nextCriteria),
    };
    syncControlSets();
    applyLocalFilters();
  };

  const syncControlSets = (sourceControlSet = null) => {
    for (const controlSet of controlSets) {
      if (sourceControlSet && controlSet === sourceControlSet) {
        continue;
      }
      writeControlStateToSet(controlSet, controlState);
    }
    renderSortHeaders();
  };

  const setSaveDefaultStatus = (message, isError = false) => {
    for (const statusElement of saveDefaultsStatuses) {
      statusElement.textContent = message;
      statusElement.style.color = isError ? "var(--danger)" : "";
    }
  };

  const readQueueDefaultsForSave = () => {
    const optionsContainer = container.querySelector("[data-result-queue-options]");
    if (!optionsContainer) {
      return {
        default_sequential_download: null,
        default_first_last_piece_prio: null,
      };
    }
    const sequentialInput = optionsContainer.querySelector('[data-result-queue-option="sequential"]');
    const firstLastInput = optionsContainer.querySelector('[data-result-queue-option="first_last_piece_prio"]');
    return {
      default_sequential_download: sequentialInput ? Boolean(sequentialInput.checked) : null,
      default_first_last_piece_prio: firstLastInput ? Boolean(firstLastInput.checked) : null,
    };
  };

  const syncReleaseYearFieldState = () => {
    if (!releaseYearInput) {
      return;
    }
    const includeYear = Boolean(includeReleaseYearInput?.checked);
    releaseYearInput.disabled = !includeYear;
  };

  const syncSearchQualityVisibility = () => {
    const mediaType = mediaTypeInput?.value || "series";
    form.querySelectorAll("[data-search-quality-group]").forEach((groupElement) => {
      const groupScope = (groupElement.dataset.mediaTypes || "").split(",");
      const groupVisible = mediaTypeMatchesScope(mediaType, groupScope);
      groupElement.hidden = !groupVisible;
    });
    form.querySelectorAll("[data-search-quality-option]").forEach((optionElement) => {
      const optionScope = (optionElement.dataset.mediaTypes || "").split(",");
      const optionVisible = mediaTypeMatchesScope(mediaType, optionScope);
      optionElement.hidden = !optionVisible;
      optionElement.querySelectorAll('input[name="quality_include_tokens"], input[name="quality_exclude_tokens"]').forEach((input) => {
        if (!optionVisible && input.checked) {
          input.checked = false;
        }
        input.disabled = !optionVisible;
      });
      if (!optionVisible) {
        setQualityTokenSliderMode(optionElement, "off", true);
      }
    });
    qualityTokenControls.syncFromStateInputs();
  };

  const getSearchPatternPreviewValue = () => {
    const tokenState = resolveSearchTokenKeywordState();
    const anyKeywordGroups = parseSearchAnyKeywordGroups(keywordsAnyInput?.value || "");
    if (tokenState.includeKeywordTerms.length > 0) {
      anyKeywordGroups.push(tokenState.includeKeywordTerms);
    }
    return deriveGeneratedPattern({
      title: queryInput?.value || "",
      useRegex: true,
      includeReleaseYear: Boolean(includeReleaseYearInput?.checked),
      releaseYear: releaseYearInput?.value || "",
      additionalIncludes: keywordsAllInput?.value || "",
      additionalExcludes: tokenState.manualKeywordsNot,
      additionalIncludeGroups: anyKeywordGroups,
      startSeason: startSeasonInput?.value || "",
      startEpisode: startEpisodeInput?.value || "",
      jellyfinSearchExistingUnseen: getJellyfinSearchExistingUnseen(),
      jellyfinExistingEpisodeNumbers: getJellyfinExistingEpisodeNumbers(),
      qualityIncludeTokens: tokenState.includeKeywordTokens,
      qualityExcludeTokens: tokenState.excludeKeywordTokens,
      qualityPatternMap,
      qualityTokenGroupMap,
    });
  };

  const refreshSearchPatternPreview = () => {
    if (!searchPatternPreview) {
      return;
    }
    searchPatternPreview.value = getSearchPatternPreviewValue();
  };

  const getLocalPatternForFilters = () => {
    const manualMustContainValue = String(mustContainOverrideInput?.value || "").trim();
    const startSeasonValue = String(startSeasonInput?.value || "").trim();
    const startEpisodeValue = String(startEpisodeInput?.value || "").trim();
    const normalizedStartSeason = normalizeBoundedPositiveInt(startSeasonValue, { min: 1, max: 99 });
    const normalizedStartEpisode = normalizeBoundedPositiveInt(startEpisodeValue, { min: 0, max: 99 });
    if (!manualMustContainValue && (normalizedStartSeason === null || normalizedStartEpisode === null)) {
      return "";
    }
    if (looksLikeFullMustContainOverride(manualMustContainValue)) {
      return manualMustContainValue;
    }
    return anchorGeneratedPatternAtStart(deriveGeneratedPattern({
      title: "",
      useRegex: true,
      includeReleaseYear: false,
      releaseYear: "",
      additionalIncludes: "",
      additionalExcludes: "",
      manualMustContain: manualMustContainValue,
      startSeason: startSeasonValue,
      startEpisode: startEpisodeValue,
      jellyfinSearchExistingUnseen: getJellyfinSearchExistingUnseen(),
      jellyfinExistingEpisodeNumbers: getJellyfinExistingEpisodeNumbers(),
      qualityIncludeTokens: [],
      qualityExcludeTokens: [],
      qualityPatternMap,
      qualityTokenGroupMap,
    }));
  };

  const getActiveFilters = () => {
    const tokenState = resolveSearchTokenKeywordState();
    const includeKeywordGroups = parseAdditionalKeywordAlternativeGroups(keywordsAllInput?.value || "");
    const requiredIncludeKeywords = includeKeywordGroups
      .filter((group) => group.length === 1)
      .map((group) => group[0]);
    const includeAnyGroups = includeKeywordGroups.filter((group) => group.length > 1);
    const keywordsAnyGroups = parseSearchAnyKeywordGroups(keywordsAnyInput?.value || "");
    keywordsAnyGroups.unshift(...includeAnyGroups);
    if (tokenState.includeKeywordTerms.length > 0) {
      keywordsAnyGroups.push(tokenState.includeKeywordTerms);
    }

    const explicitIndexerFilters = parseSearchFilterList(filterIndexersInput?.value || "")
      .map((item) => item.toLocaleLowerCase());
    const feedScopedIndexers = hasFeedSelectionConstraint() ? getSelectedFeedIndexerSlugs() : [];
    const feedScopeBlocksAll = hasFeedSelectionConstraint() && feedScopedIndexers.length === 0;
    let selectedIndexers = [...explicitIndexerFilters];
    if (feedScopedIndexers.length > 0) {
      if (selectedIndexers.length === 0) {
        selectedIndexers = [...feedScopedIndexers];
      } else {
        const allowedFeedKeys = new Set(mergeUniqueIndexerVariantKeys(feedScopedIndexers));
        selectedIndexers = selectedIndexers.filter((value) => {
          const variantKeys = buildIndexerKeyVariants(value);
          return variantKeys.some((item) => allowedFeedKeys.has(item));
        });
      }
    }

    return {
      query: getSearchQuery(),
      imdbId: getSearchImdbId(),
      releaseYear: includeReleaseYearInput?.checked
        ? normalizeReleaseYear(releaseYearInput?.value || "")
        : "",
      keywordsAll: requiredIncludeKeywords,
      keywordsAnyGroups,
      keywordsNot: mergeUniqueTerms(
        tokenState.manualKeywordsNot,
        tokenState.excludeKeywordTerms
      ),
      qualityIncludeTokens: tokenState.includeKeywordTokens,
      qualityExcludeTokens: tokenState.excludeKeywordTokens,
      qualityIncludeRegex: tokenState.includeKeywordRegex,
      qualityExcludeRegex: tokenState.excludeKeywordRegex,
      generatedPatternRegex: compileGeneratedPatternRegex(getLocalPatternForFilters()),
      manualMustContain: String(mustContainOverrideInput?.value || "").trim(),
      startSeason: normalizeBoundedPositiveInt(startSeasonInput?.value || "", { min: 1, max: 99 }),
      startEpisode: normalizeBoundedPositiveInt(startEpisodeInput?.value || "", { min: 0, max: 99 }),
      sizeMinMb: parseSearchMb(sizeMinInput?.value || ""),
      sizeMaxMb: parseSearchMb(sizeMaxInput?.value || ""),
      feedScopeBlocksAll,
      feedScopedIndexers,
      feedScopedIndexerVariantKeys: mergeUniqueIndexerVariantKeys(feedScopedIndexers),
      explicitIndexers: explicitIndexerFilters,
      indexers: selectedIndexers,
      indexerVariantKeys: mergeUniqueIndexerVariantKeys(selectedIndexers),
      categories: parseSearchFilterList(filterCategoryIdsInput?.value || "")
        .map((item) => normalizeCategoryFilterValue(item))
        .filter(Boolean),
    };
  };

  const buildFilterValues = (filters) => {
    const values = [];
    if (filters.releaseYear) {
      values.push({
        kind: "release_year",
        label: `Release year = ${filters.releaseYear}`,
        value: filters.releaseYear,
      });
    }
    for (const keyword of filters.keywordsAll) {
      values.push({
        kind: "keywords_all",
        label: `Extra include keyword: ${keyword}`,
        value: keyword,
        matchKey: normalizeSearchText(keyword),
      });
    }
    for (const [groupIndex, group] of filters.keywordsAnyGroups.entries()) {
      const groupLabel = group.join(" | ");
      const groupMatchKey = group.map((item) => normalizeSearchText(item)).filter(Boolean).join("||");
      values.push({
        kind: "keywords_any_group",
        label: `Any-of group ${groupIndex + 1}: ${groupLabel}`,
        value: [...group],
        matchKey: groupMatchKey,
      });
    }
    for (const keyword of filters.keywordsNot) {
      values.push({
        kind: "keywords_not",
        label: `mustNotContain: ${keyword}`,
        value: keyword,
        matchKey: normalizeSearchText(keyword),
      });
    }
    for (const token of filters.qualityIncludeTokens || []) {
      values.push({
        kind: "quality_include_token",
        label: `Tag include: ${token}`,
        value: token,
        matchKey: normalizeSearchText(token),
      });
    }
    for (const token of filters.qualityExcludeTokens || []) {
      values.push({
        kind: "quality_exclude_token",
        label: `Tag exclude: ${token}`,
        value: token,
        matchKey: normalizeSearchText(token),
      });
    }
    if (filters.startSeason !== null && filters.startEpisode !== null) {
      values.push({
        kind: "episode_progress_floor",
        label: `Episode floor: S${filters.startSeason}E${filters.startEpisode}`,
        value: `${filters.startSeason}:${filters.startEpisode}`,
      });
    }
    if (filters.manualMustContain) {
      const compactRegexValue = filters.manualMustContain.length > 96
        ? `${filters.manualMustContain.slice(0, 93)}...`
        : filters.manualMustContain;
      values.push({
        kind: "manual_must_contain",
        label: `Regex fragments: ${compactRegexValue}`,
        value: filters.manualMustContain,
      });
    }
    if (filters.sizeMinMb !== null) {
      values.push({
        kind: "size_min_mb",
        label: `Minimum size >= ${filters.sizeMinMb} MB`,
        value: filters.sizeMinMb,
      });
    }
    if (filters.sizeMaxMb !== null) {
      values.push({
        kind: "size_max_mb",
        label: `Maximum size <= ${filters.sizeMaxMb} MB`,
        value: filters.sizeMaxMb,
      });
    }
    if (filters.feedScopeBlocksAll) {
      values.push({
        kind: "feed_scope_none",
        label: "Affected feeds: none selected",
        value: true,
      });
    }
    const explicitIndexers = filters.explicitIndexers || filters.indexers;
    for (const indexer of explicitIndexers) {
      values.push({
        kind: "filter_indexer",
        label: `Indexer = ${indexer}`,
        value: indexer,
      });
    }
    for (const categoryId of filters.categories) {
      values.push({
        kind: "filter_category",
        label: `Category = ${categoryId}`,
        value: categoryId,
      });
    }
    return values;
  };

  const serializeKeywordGroups = (groups) => groups.map((group) => group.join("|")).join("\n");
  const serializeAnyKeywordGroups = (groups) => groups.map((group) => group.join(", ")).join(" | ");

  const setHiddenMultiselectValues = (input, values) => {
    if (!input) {
      return;
    }
    input.value = values.join(", ");
  };

  const removeFilterValueFromInputs = (filterValue) => {
    if (filterValue.kind === "release_year") {
      if (includeReleaseYearInput) {
        includeReleaseYearInput.checked = false;
      }
      if (releaseYearInput) {
        releaseYearInput.value = "";
      }
      return;
    }

    if (filterValue.kind === "keywords_all" && keywordsAllInput) {
      const nextGroups = parseAdditionalKeywordAlternativeGroups(keywordsAllInput.value || "").filter(
        (group) => !(group.length === 1 && normalizeSearchText(group[0]) === filterValue.matchKey)
      );
      keywordsAllInput.value = serializeKeywordGroups(nextGroups);
      return;
    }

    if (filterValue.kind === "keywords_any_group") {
      let removed = false;
      if (keywordsAnyInput) {
        const anyGroups = parseSearchAnyKeywordGroups(keywordsAnyInput.value || "");
        const nextAnyGroups = anyGroups.filter(
          (group) => group.map((item) => normalizeSearchText(item)).filter(Boolean).join("||") !== filterValue.matchKey
        );
        if (nextAnyGroups.length !== anyGroups.length) {
          keywordsAnyInput.value = serializeAnyKeywordGroups(nextAnyGroups);
          removed = true;
        }
      }
      if (!removed && keywordsAllInput) {
        const includeGroups = parseAdditionalKeywordAlternativeGroups(keywordsAllInput.value || "");
        const nextGroups = includeGroups.filter(
          (group) => !(group.length > 1 && group.map((item) => normalizeSearchText(item)).filter(Boolean).join("||") === filterValue.matchKey)
        );
        keywordsAllInput.value = serializeKeywordGroups(nextGroups);
      }
      return;
    }

    if (filterValue.kind === "keywords_not" && keywordsNotInput) {
      const nextGroups = [];
      for (const group of parseAdditionalKeywordAlternativeGroups(keywordsNotInput.value || "")) {
        const keptTerms = group.filter((item) => normalizeSearchText(item) !== filterValue.matchKey);
        if (keptTerms.length > 0) {
          nextGroups.push(keptTerms);
        }
      }
      keywordsNotInput.value = serializeKeywordGroups(nextGroups);
      return;
    }

    if (filterValue.kind === "quality_include_token") {
      const includeInput = Array.from(form.querySelectorAll('input[name="quality_include_tokens"]')).find(
        (input) => input.value === String(filterValue.value || "")
      );
      if (includeInput) {
        includeInput.checked = false;
      }
      return;
    }

    if (filterValue.kind === "quality_exclude_token") {
      const excludeInput = Array.from(form.querySelectorAll('input[name="quality_exclude_tokens"]')).find(
        (input) => input.value === String(filterValue.value || "")
      );
      if (excludeInput) {
        excludeInput.checked = false;
      }
      return;
    }

    if (filterValue.kind === "episode_progress_floor") {
      if (startSeasonInput) {
        startSeasonInput.value = "";
      }
      if (startEpisodeInput) {
        startEpisodeInput.value = "";
      }
      return;
    }

    if (filterValue.kind === "manual_must_contain" && mustContainOverrideInput) {
      mustContainOverrideInput.value = "";
      return;
    }

    if (filterValue.kind === "size_min_mb" && sizeMinInput) {
      sizeMinInput.value = "";
      return;
    }

    if (filterValue.kind === "size_max_mb" && sizeMaxInput) {
      sizeMaxInput.value = "";
      return;
    }

    if (filterValue.kind === "feed_scope_none") {
      getFeedUrlInputs().forEach((input) => {
        input.checked = true;
      });
      return;
    }

    if (filterValue.kind === "filter_indexer") {
      const keptValues = parseStoredMultiselectValues(
        filterIndexersInput,
        (value) => String(value || "").trim().toLocaleLowerCase()
      )
        .filter((item) => item.key !== String(filterValue.value || "").trim().toLocaleLowerCase())
        .map((item) => item.value);
      setHiddenMultiselectValues(filterIndexersInput, keptValues);
      return;
    }

    if (filterValue.kind === "filter_category") {
      const keptValues = parseStoredMultiselectValues(filterCategoryIdsInput, normalizeCategoryFilterValue)
        .filter((item) => item.key !== normalizeCategoryFilterValue(filterValue.value || ""))
        .map((item) => item.value);
      setHiddenMultiselectValues(filterCategoryIdsInput, keptValues);
    }
  };

  const clearLocalFilters = () => {
    if (includeReleaseYearInput) {
      includeReleaseYearInput.checked = false;
    }
    if (releaseYearInput) {
      releaseYearInput.value = "";
    }
    if (keywordsAllInput) {
      keywordsAllInput.value = "";
    }
    if (keywordsAnyInput) {
      keywordsAnyInput.value = "";
    }
    if (keywordsNotInput) {
      keywordsNotInput.value = "";
    }
    if (mustContainOverrideInput) {
      mustContainOverrideInput.value = "";
    }
    if (startSeasonInput) {
      startSeasonInput.value = "";
    }
    if (startEpisodeInput) {
      startEpisodeInput.value = "";
    }
    if (sizeMinInput) {
      sizeMinInput.value = "";
    }
    if (sizeMaxInput) {
      sizeMaxInput.value = "";
    }
    setCheckedValues(form, "quality_include_tokens", []);
    setCheckedValues(form, "quality_exclude_tokens", []);
    setHiddenMultiselectValues(filterIndexersInput, []);
    setHiddenMultiselectValues(filterCategoryIdsInput, []);
    syncReleaseYearFieldState();
  };

  const renderActiveFilterChips = (filters) => {
    const activeValues = buildFilterValues(filters);
    for (const controlSet of controlSets) {
      const chipList = controlSet.activeFilterList;
      const chipContainer = controlSet.activeFiltersContainer;
      if (!chipList || !chipContainer) {
        continue;
      }
      chipList.innerHTML = "";
      for (const filterValue of activeValues) {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "search-active-filter-chip";
        chip.textContent = `× ${filterValue.label}`;
        chip.addEventListener("click", () => {
          removeFilterValueFromInputs(filterValue);
          qualityTokenControls.syncFromStateInputs();
          applyLocalFilters();
        });
        chipList.appendChild(chip);
      }
      chipContainer.hidden = activeValues.length === 0;
    }
  };

  const matchesStructuredKeywordToken = (textSurface, normalizedTerm) => {
    const tokens = textSurface.split(" ").filter(Boolean);
    const seasonEpisodeMatch = normalizedTerm.match(/^s0*(\d{1,2})e0*(\d{1,3})$/u);
    if (seasonEpisodeMatch) {
      const season = Number(seasonEpisodeMatch[1]);
      const episode = Number(seasonEpisodeMatch[2]);
      const variants = [
        `s${season}e${episode}`,
        `s${String(season).padStart(2, "0")}e${episode}`,
        `s${season}e${String(episode).padStart(2, "0")}`,
        `s${String(season).padStart(2, "0")}e${String(episode).padStart(2, "0")}`,
      ];
      if (tokens.some((token) => variants.includes(token))) {
        return true;
      }
      const seasonVariants = [String(season), String(season).padStart(2, "0")];
      const episodeVariants = [String(episode), String(episode).padStart(2, "0")];
      return seasonVariants.some((seasonVariant) => (
        episodeVariants.some((episodeVariant) => (
          textSurface.includes(`season ${seasonVariant} episode ${episodeVariant}`)
          || textSurface.includes(`season ${seasonVariant} ep ${episodeVariant}`)
          || textSurface.includes(`s ${seasonVariant} e ${episodeVariant}`)
        ))
      ));
    }
    const seasonMatch = normalizedTerm.match(/^s0*(\d{1,2})$/u);
    if (seasonMatch) {
      const season = Number(seasonMatch[1]);
      const variants = [`s${season}`, `s${String(season).padStart(2, "0")}`];
      if (tokens.some((token) => {
        if (variants.includes(token)) {
          return true;
        }
        return variants.some((variant) => {
          if (!token.startsWith(`${variant}e`) || token.length <= variant.length + 1) {
            return false;
          }
          const suffix = token.slice(variant.length + 1);
          return /^\d+$/u.test(suffix);
        });
      })) {
        return true;
      }
      const seasonVariants = [String(season), String(season).padStart(2, "0")];
      return seasonVariants.some((seasonVariant) => (
        textSurface.includes(`season ${seasonVariant}`)
        || textSurface.includes(`s ${seasonVariant}`)
      ));
    }
    const episodeMatch = normalizedTerm.match(/^e0*(\d{1,3})$/u);
    if (episodeMatch) {
      const episode = Number(episodeMatch[1]);
      const variants = [`e${episode}`, `e${String(episode).padStart(2, "0")}`];
      if (tokens.some((token) => {
        if (variants.includes(token)) {
          return true;
        }
        if (!token.startsWith("s") || token.indexOf("e", 1) === -1) {
          return false;
        }
        const eIndex = token.indexOf("e", 1);
        const seasonToken = token.slice(1, eIndex);
        const episodeToken = token.slice(eIndex + 1);
        if (!/^\d+$/u.test(seasonToken) || !/^\d+$/u.test(episodeToken)) {
          return false;
        }
        return Number(episodeToken) === episode;
      })) {
        return true;
      }
      const episodeVariants = [String(episode), String(episode).padStart(2, "0")];
      return episodeVariants.some((episodeVariant) => (
        textSurface.includes(`episode ${episodeVariant}`)
        || textSurface.includes(`ep ${episodeVariant}`)
        || textSurface.includes(`e ${episodeVariant}`)
      ));
    }
    return false;
  };

  const containsTerm = (textSurface, term) => {
    const normalizedTerm = normalizeSearchText(term);
    if (!normalizedTerm) {
      return false;
    }
    if (matchesStructuredKeywordToken(textSurface, normalizedTerm)) {
      return true;
    }
    if (!normalizedTerm.includes(" ") && normalizedTerm.length <= 3) {
      const paddedSurface = ` ${textSurface} `;
      return paddedSurface.includes(` ${normalizedTerm} `);
    }
    return textSurface.includes(normalizedTerm);
  };

  const containsExcludedTerm = (textSurface, term) => {
    const normalizedTerm = normalizeSearchText(term);
    if (!normalizedTerm) {
      return false;
    }
    if (!normalizedTerm.includes(" ") && normalizedTerm.length <= 2) {
      const paddedSurface = ` ${textSurface} `;
      return paddedSurface.includes(` ${normalizedTerm} `);
    }
    return textSurface.includes(normalizedTerm);
  };

  const matchesQueryText = (titleSurface, queryValue) => {
    const normalizedQuery = normalizeSearchText(queryValue);
    if (!normalizedQuery) {
      return true;
    }
    if (titleSurface.includes(normalizedQuery)) {
      return true;
    }
    const queryTerms = normalizedQuery.split(" ").filter(Boolean);
    if (queryTerms.length === 0) {
      return true;
    }
    const titleTerms = new Set(titleSurface.split(" ").filter(Boolean));
    return queryTerms.every((item) => titleTerms.has(item));
  };
  const PRECISE_TITLE_SEGMENT_SPLIT_RE = /[|/()[\]]+/u;
  const PRECISE_TITLE_ALLOWED_POSTFIX_TOKENS = new Set([
    "aac",
    "ac3",
    "atmos",
    "av1",
    "avc",
    "avo",
    "bdrip",
    "bluray",
    "blu",
    "cam",
    "christmas",
    "complete",
    "criterion",
    "director",
    "dub",
    "dts",
    "dv",
    "dvd",
    "dvdrip",
    "eng",
    "ep",
    "episode",
    "extended",
    "finale",
    "h264",
    "h265",
    "hdtv",
    "hevc",
    "hdr",
    "hdr10",
    "imax",
    "limited",
    "multi",
    "mvo",
    "pack",
    "pilot",
    "ray",
    "remux",
    "repack",
    "rus",
    "season",
    "series",
    "special",
    "sub",
    "telecine",
    "truehd",
    "uhd",
    "uncut",
    "ukr",
    "unrated",
    "web",
    "webdl",
    "webrip",
    "x264",
    "x265",
    "xmas",
  ]);
  const YEAR_TOKEN_RE = /^\d{4}$/u;
  const SEASON_TOKEN_RE = /^s0*\d{1,2}$/u;
  const EPISODE_TOKEN_RE = /^e0*\d{1,3}$/u;
  const SEASON_EPISODE_TOKEN_RE = /^s0*\d{1,2}e0*\d{1,3}$/u;
  const X_SEASON_EPISODE_TOKEN_RE = /^\d{1,2}x\d{1,3}$/u;
  const buildPreciseTitleSegments = (title) => {
    const segments = [];
    const seen = new Set();
    for (const rawSegment of String(title || "").split(PRECISE_TITLE_SEGMENT_SPLIT_RE)) {
      const candidate = String(rawSegment || "").trim();
      if (!candidate) {
        continue;
      }
      const normalized = normalizeSearchText(candidate);
      if (!normalized || seen.has(normalized)) {
        continue;
      }
      seen.add(normalized);
      segments.push(candidate);
    }
    return segments.length ? segments : [String(title || "")];
  };
  const isAllowedPreciseTitleSuffixToken = (token) => {
    const normalized = normalizeSearchText(token);
    if (!normalized) {
      return true;
    }
    if (YEAR_TOKEN_RE.test(normalized)) {
      return true;
    }
    if (SEASON_TOKEN_RE.test(normalized) || EPISODE_TOKEN_RE.test(normalized)) {
      return true;
    }
    if (SEASON_EPISODE_TOKEN_RE.test(normalized) || X_SEASON_EPISODE_TOKEN_RE.test(normalized)) {
      return true;
    }
    return PRECISE_TITLE_ALLOWED_POSTFIX_TOKENS.has(normalized);
  };
  const segmentMatchesPreciseTitleIdentity = (segment, queryValue) => {
    const normalizedSegment = normalizeSearchText(segment);
    const normalizedQuery = normalizeSearchText(queryValue);
    if (!normalizedSegment || !normalizedQuery) {
      return false;
    }
    if (normalizedSegment === normalizedQuery) {
      return true;
    }
    if (!normalizedSegment.startsWith(normalizedQuery)) {
      return false;
    }
    const suffix = normalizedSegment.slice(normalizedQuery.length).trim();
    if (!suffix) {
      return true;
    }
    const firstToken = suffix.split(" ", 1)[0];
    return isAllowedPreciseTitleSuffixToken(firstToken);
  };
  const matchesPreciseTitleIdentity = (title, queryValue) => {
    return buildPreciseTitleSegments(title).some((segment) => (
      segmentMatchesPreciseTitleIdentity(segment, queryValue)
    ));
  };

  const groupLabel = (group) => group.map((item) => String(item || "").trim()).filter(Boolean).join(" | ");
  const searchScopeSummaryText = (filters) => {
    const scopeParts = [];
    const queryLabel = getSearchQueryLabel();
    if (queryLabel) {
      scopeParts.push(`query "${queryLabel}"`);
    }
    if (filters.imdbId) {
      scopeParts.push(`IMDb ${filters.imdbId}`);
    }
    if (filters.feedScopedIndexers && filters.feedScopedIndexers.length > 0) {
      scopeParts.push(`affected feed indexers ${filters.feedScopedIndexers.join(", ")}`);
    }
    if (scopeParts.length === 0) {
      return "";
    }
    return `Current scope still includes ${scopeParts.join("; ")}.`;
  };

  const entryFilterFailure = (entry, filters) => {
    if (filters.feedScopeBlocksAll) {
      return "No affected feeds are selected.";
    }

    const payloadImdbId = normalizeSearchImdbId(filters.imdbId || "");
    const resultImdbId = normalizeSearchImdbId(entry.imdbId || "");
    const imdbExactMatch = Boolean(payloadImdbId && resultImdbId && payloadImdbId === resultImdbId);
    const isPrecisePrimaryRow = Boolean(
      payloadImdbId && effectiveQuerySourceKeys(entry, filters).includes("primary")
    );
    if (!isPrecisePrimaryRow && !imdbExactMatch && !matchesQueryText(entry.titleSurface, filters.query)) {
      const queryLabel = getSearchQueryLabel();
      return queryLabel
        ? `Title does not match query "${queryLabel}".`
        : "Title does not match the current query.";
    }
    if (!isPrecisePrimaryRow) {
      for (const keyword of filters.keywordsAll) {
        if (!containsTerm(entry.textSurface, keyword)) {
          return `Missing include keyword: ${keyword}.`;
        }
      }

      for (const [groupIndex, group] of filters.keywordsAnyGroups.entries()) {
        if (!group.some((keyword) => containsTerm(entry.textSurface, keyword))) {
          return `Missing any-of group ${groupIndex + 1}: ${groupLabel(group)}.`;
        }
      }

      for (const keyword of filters.keywordsNot) {
        if (containsExcludedTerm(entry.textSurface, keyword)) {
          return `Matched excluded keyword: ${keyword}.`;
        }
      }
    }

    if (filters.qualityIncludeRegex && !filters.qualityIncludeRegex.test(entry.regexSurface)) {
      return "Missing required quality tags.";
    }
    if (filters.qualityExcludeRegex && filters.qualityExcludeRegex.test(entry.regexSurface)) {
      return "Matched an excluded quality tag.";
    }
    if (!isPrecisePrimaryRow && filters.generatedPatternRegex && !filters.generatedPatternRegex.test(entry.regexSurface)) {
      return "Does not match the generated rule pattern.";
    }

    if (filters.releaseYear) {
      if (!entry.year || entry.year !== filters.releaseYear) {
        return `Release year does not match ${filters.releaseYear}.`;
      }
    }

    if (filters.sizeMinMb !== null || filters.sizeMaxMb !== null) {
      if (entry.sizeBytes === null) {
        return "Missing size data for the current size filter.";
      }
      const sizeMb = entry.sizeBytes / (1024 * 1024);
      if (filters.sizeMinMb !== null && sizeMb < filters.sizeMinMb) {
        return `Smaller than the minimum size (${filters.sizeMinMb} MB).`;
      }
      if (filters.sizeMaxMb !== null && sizeMb > filters.sizeMaxMb) {
        return `Larger than the maximum size (${filters.sizeMaxMb} MB).`;
      }
    }

    if (filters.feedScopedIndexers && filters.feedScopedIndexers.length > 0) {
      const allowedFeedKeys = new Set(
        filters.feedScopedIndexerVariantKeys && filters.feedScopedIndexerVariantKeys.length > 0
          ? filters.feedScopedIndexerVariantKeys
          : mergeUniqueIndexerVariantKeys(filters.feedScopedIndexers)
      );
      if (!entry.indexerKeys.some((item) => allowedFeedKeys.has(item))) {
        return "Indexer is outside the affected-feed scope.";
      }
    }

    if (filters.indexers.length > 0) {
      const allowedIndexerKeys = new Set(
        filters.indexerVariantKeys && filters.indexerVariantKeys.length > 0
          ? filters.indexerVariantKeys
          : mergeUniqueIndexerVariantKeys(filters.indexers)
      );
      if (!entry.indexerKeys.some((item) => allowedIndexerKeys.has(item))) {
        return "Indexer is outside the current indexer scope.";
      }
    }

    if (filters.categories.length > 0) {
      if (
        entry.categoryValues.length === 0
        || !entry.categoryValues.some((item) => filters.categories.includes(item))
      ) {
        return "Category is outside the current category scope.";
      }
    }

    return null;
  };

  const entryMatchesFilters = (entry, filters) => {
    return entryFilterFailure(entry, filters) === null;
  };

  const effectiveQuerySourceKeys = (entry, filters) => {
    const baseKeys = Array.isArray(entry.querySourceKeys) ? entry.querySourceKeys : [];
    if (!baseKeys.includes("primary")) {
      return baseKeys;
    }
    const payloadImdbId = normalizeSearchImdbId(filters.imdbId || "");
    const resultImdbId = normalizeSearchImdbId(entry.imdbId || "");
    const imdbExactMatch = Boolean(payloadImdbId && resultImdbId && payloadImdbId === resultImdbId);
    if (!payloadImdbId || imdbExactMatch || matchesPreciseTitleIdentity(entry.title, filters.query)) {
      return baseKeys;
    }
    const demotedKeys = baseKeys.filter((item) => item !== "primary");
    if (!demotedKeys.includes("fallback")) {
      demotedKeys.push("fallback");
    }
    return demotedKeys;
  };

  const effectiveQuerySourcePriority = (entry, filters) => {
    return querySourcePriority(effectiveQuerySourceKeys(entry, filters));
  };

  const effectiveQuerySourcePresentation = (entry, filters) => {
    const sourceKeys = effectiveQuerySourceKeys(entry, filters);
    const hasPrimary = sourceKeys.includes("primary");
    const hasFallback = sourceKeys.includes("fallback");
    if (hasPrimary && hasFallback) {
      return {
        key: "primary+fallback",
        label: entry.querySourceLabel || "Precise results + Title fallback",
      };
    }
    if (hasPrimary) {
      return {
        key: "primary",
        label: entry.querySourceLabelPrimary || entry.querySourceLabel || "Precise results",
      };
    }
    if (hasFallback) {
      return {
        key: "fallback",
        label: entry.querySourceLabelFallback || "Title fallback",
      };
    }
    return {
      key: String(entry.querySourceKey || "").trim().toLowerCase(),
      label: entry.querySourceLabel || "Primary query",
    };
  };

  const getSortCriteria = () => {
    return controlState.sortCriteria;
  };

  const compareEntries = (left, right, criteria, filters) => {
    const leftQueryPriority = effectiveQuerySourcePriority(left, filters);
    const rightQueryPriority = effectiveQuerySourcePriority(right, filters);
    if (leftQueryPriority !== rightQueryPriority) {
      return leftQueryPriority - rightQueryPriority;
    }

    const compareValue = (field) => {
      if (field === "size_bytes") {
        return { type: "number", left: left.sizeBytes, right: right.sizeBytes };
      }
      if (field === "published_at") {
        return { type: "number", left: left.publishedAtMs, right: right.publishedAtMs };
      }
      if (field === "year") {
        return {
          type: "number",
          left: parseOptionalNumber(left.year),
          right: parseOptionalNumber(right.year),
        };
      }
      if (field === "seeders") {
        return { type: "number", left: left.seeders, right: right.seeders };
      }
      if (field === "peers") {
        return { type: "number", left: left.peers, right: right.peers };
      }
      if (field === "leechers") {
        return { type: "number", left: left.leechers, right: right.leechers };
      }
      if (field === "grabs") {
        return { type: "number", left: left.grabs, right: right.grabs };
      }
      if (field === "indexer") {
        return { type: "string", left: left.indexer || "", right: right.indexer || "" };
      }
      return { type: "string", left: left.title || "", right: right.title || "" };
    };

    for (const criterion of criteria) {
      const compared = compareValue(criterion.field);
      const leftMissing = compared.left === null || compared.left === "";
      const rightMissing = compared.right === null || compared.right === "";
      if (leftMissing && rightMissing) {
        continue;
      }
      if (leftMissing) {
        return 1;
      }
      if (rightMissing) {
        return -1;
      }

      let result = 0;
      if (compared.type === "number") {
        result = compared.left < compared.right ? -1 : (compared.left > compared.right ? 1 : 0);
      } else {
        result = String(compared.left).localeCompare(String(compared.right), undefined, { sensitivity: "base" });
      }
      if (result !== 0) {
        return criterion.direction === "desc" ? -result : result;
      }
    }

    return left.originalIndex - right.originalIndex;
  };

  const sectionCandidates = [
    ...Array.from(container.querySelectorAll("[data-search-results]")).map((element) => element.dataset.searchResults),
    ...Array.from(container.querySelectorAll("[data-search-table-wrap]")).map((element) => element.dataset.searchTableWrap),
    ...Array.from(container.querySelectorAll("[data-search-summary]")).map((element) => element.dataset.searchSummary),
    ...Array.from(container.querySelectorAll("[data-search-card]")).map((element) => element.dataset.searchCard),
    ...Array.from(container.querySelectorAll("[data-search-row]")).map((element) => element.dataset.searchRow),
  ];
  const sections = [];
  const seenSections = new Set();
  for (const candidate of sectionCandidates) {
    const normalized = String(candidate || "").trim();
    if (!normalized || seenSections.has(normalized)) {
      continue;
    }
    seenSections.add(normalized);
    sections.push(normalized);
  }
  const parseQuerySourceKeys = (value) => {
    const cleaned = String(value || "").trim().toLocaleLowerCase();
    if (!cleaned) {
      return [];
    }
    if (cleaned === "primary+fallback") {
      return ["primary", "fallback"];
    }
    if (cleaned === "primary" || cleaned === "fallback") {
      return [cleaned];
    }
    if (cleaned.includes("title fallback")) {
      if (
        cleaned.includes("imdb-first")
        || cleaned.includes("precise results")
        || cleaned.includes("rule search results")
      ) {
        return ["primary", "fallback"];
      }
      return ["fallback"];
    }
    if (
      cleaned.includes("imdb-first")
      || cleaned.includes("precise results")
      || cleaned.includes("rule search results")
      || cleaned.includes("primary")
    ) {
      return ["primary"];
    }
    return cleaned
      .split("+")
      .map((item) => item.trim())
      .filter((item) => item === "primary" || item === "fallback");
  };
  const querySourcePriority = (keys) => {
    const normalizedKeys = Array.isArray(keys) ? keys : [];
    const hasPrimary = normalizedKeys.includes("primary");
    const hasFallback = normalizedKeys.includes("fallback");
    if (hasPrimary && hasFallback) {
      return 1;
    }
    if (hasPrimary) {
      return 0;
    }
    if (hasFallback) {
      return 2;
    }
    return 9;
  };

  const sectionState = Object.fromEntries(
    sections.map((section) => {
      const cardContainer = container.querySelector(`[data-search-results="${section}"]`);
      const cards = Array.from(container.querySelectorAll(`[data-search-card="${section}"]`));
      const tableWrap = container.querySelector(`[data-search-table-wrap="${section}"]`);
      const tableBody = container.querySelector(`[data-search-table-body="${section}"]`);
      const rows = Array.from(container.querySelectorAll(`[data-search-row="${section}"]`));
      const entries = cards.map((card, index) => ({
        originalIndex: index,
        card,
        row: rows[index] || null,
        visibilityStatusElement: rows[index]?.querySelector("[data-search-visibility-status]") || null,
        title: String(card.dataset.title || "").trim(),
        titleSurface: normalizeSearchText(card.dataset.title || ""),
        textSurface: normalizeSearchText(card.dataset.textSurface || ""),
        // Generated-pattern regex should evaluate against the raw title text so
        // season/episode range separators like "S03E01-07" are preserved.
        regexSurface: String(card.dataset.title || card.dataset.textSurface || "").trim(),
        imdbId: normalizeSearchImdbId(card.dataset.imdbId || ""),
        indexerRaw: String(card.dataset.indexer || "").trim(),
        indexer: String(card.dataset.indexer || "").trim().toLocaleLowerCase(),
        indexerKeys: buildIndexerKeyVariants(card.dataset.indexer || ""),
        sizeBytes: parseOptionalNumber(card.dataset.sizeBytes),
        publishedAtMs: parseIsoDateMs(card.dataset.publishedAt),
        year: normalizeReleaseYear(card.dataset.year || card.dataset.title || ""),
        seeders: parseOptionalNumber(card.dataset.seeders),
        peers: parseOptionalNumber(card.dataset.peers),
        leechers: parseOptionalNumber(card.dataset.leechers),
        grabs: parseOptionalNumber(card.dataset.grabs),
        categoryIds: parseSearchFilterList(card.dataset.categoryIds || ""),
        categoryLabels: parseSearchFilterList(card.dataset.categoryLabels || ""),
        categoryValues: mergeUniqueTerms(
          parseSearchFilterList(card.dataset.categoryIds || ""),
          parseSearchFilterList(card.dataset.categoryLabels || "")
        )
          .map((item) => normalizeCategoryFilterValue(item))
          .filter(Boolean),
        querySourceKeys: parseQuerySourceKeys(
          card.dataset.querySourceKey || card.dataset.querySource || ""
        ),
        querySourceKey: String(card.dataset.querySourceKey || card.dataset.querySource || "").trim(),
        querySourceLabel: String(card.dataset.querySource || "").trim(),
        querySourceLabelPrimary:
          String(card.dataset.querySource || "").trim().split(" + ", 1)[0].trim()
          || "Precise results",
        querySourceLabelFallback:
          String(card.dataset.querySource || "").trim().includes(" + ")
            ? String(card.dataset.querySource || "").trim().split(" + ").slice(-1)[0].trim()
            : "Title fallback",
        querySourcePriority: querySourcePriority(
          parseQuerySourceKeys(card.dataset.querySourceKey || card.dataset.querySource || "")
        ),
        cardQuerySourceChipElement: card.querySelector(".rule-card-top .status-chip"),
        cardQuerySourceDetailElement: card.querySelector(".detail-list div:first-child dd"),
        rowQuerySourceElement: rows[index]?.querySelector("td:first-child") || null,
      }));

      return [
        section,
        {
          entries,
          cardContainer,
          tableWrap,
          tableBody,
          filteredCountElement: container.querySelector(`[data-search-filtered-count="${section}"]`),
          fetchedCountElement: container.querySelector(`[data-search-fetched-count="${section}"]`),
          scopeSummaryElement: container.querySelector(`[data-search-scope-summary="${section}"]`),
          hiddenSummaryElement: container.querySelector(`[data-search-hidden-summary="${section}"]`),
          emptyState: container.querySelector(`[data-search-empty="${section}"]`),
        },
      ];
    })
  );
  const sourceSummaryState = Array.from(container.querySelectorAll("[data-search-source-summary]"))
    .map((summaryElement) => {
      const key = String(summaryElement.dataset.searchSourceSummary || "").trim().toLocaleLowerCase();
      if (!key) {
        return null;
      }
      const filteredCountElement = summaryElement.querySelector("[data-search-source-filtered-count]");
      const fetchedCountElement = summaryElement.querySelector("[data-search-source-fetched-count]");
      const datasetFetchedCount = parseOptionalNumber(summaryElement.dataset.searchSourceFetched);
      const textFetchedCount = parseOptionalNumber(fetchedCountElement?.textContent || "");
      return {
        key,
        filteredCountElement,
        fetchedCountElement,
        fetchedCount: datasetFetchedCount ?? textFetchedCount ?? 0,
      };
    })
    .filter(Boolean);

  const parseStoredMultiselectValues = (input, normalizeValue) => {
    const values = [];
    const seen = new Set();
    for (const rawValue of parseSearchFilterList(input?.value || "")) {
      const key = normalizeValue(rawValue);
      if (!key || seen.has(key)) {
        continue;
      }
      seen.add(key);
      values.push({
        value: String(rawValue || "").trim(),
        key,
      });
    }
    return values;
  };

  const allEntries = sections.flatMap((section) => sectionState[section]?.entries || []);
  let applyLocalFilters = () => {};
  const noOpMultiselectController = {
    refreshOptions: () => {},
  };
  const buildDistinctIndexerOptions = () => {
    const options = [];
    const seen = new Set();
    for (const entry of allEntries) {
      const label = String(entry.indexerRaw || "").trim();
      const key = label.toLocaleLowerCase();
      if (!key || seen.has(key)) {
        continue;
      }
      seen.add(key);
      options.push({ value: label, label, key });
    }
    return options.sort((left, right) => left.label.localeCompare(right.label, undefined, { sensitivity: "base" }));
  };
  const buildDistinctCategoryOptions = () => {
    const options = [];
    const seen = new Set();
    for (const entry of allEntries) {
      const labels = (entry.categoryLabels && entry.categoryLabels.length > 0)
        ? entry.categoryLabels
        : entry.categoryIds;
      for (const labelValue of labels || []) {
        const label = String(labelValue || "").trim();
        const key = normalizeCategoryFilterValue(label);
        if (!key || seen.has(key)) {
          continue;
        }
        seen.add(key);
        options.push({ value: label, label, key });
      }
    }
    return options.sort((left, right) => left.label.localeCompare(right.label, undefined, { sensitivity: "base" }));
  };
  const buildCategoryOptionsForFilters = (filtersWithoutCategories) => {
    const optionsByKey = new Map();
    for (const entry of allEntries) {
      if (!entryMatchesFilters(entry, filtersWithoutCategories)) {
        continue;
      }
      const labels = (entry.categoryLabels && entry.categoryLabels.length > 0)
        ? entry.categoryLabels
        : entry.categoryIds;
      for (const rawLabel of labels || []) {
        const label = String(rawLabel || "").trim();
        const key = normalizeCategoryFilterValue(label);
        if (!label || !key) {
          continue;
        }
        const existing = optionsByKey.get(key);
        if (existing) {
          existing.count += 1;
          continue;
        }
        optionsByKey.set(key, {
          value: label,
          label,
          key,
          count: 1,
        });
      }
    }
    return Array.from(optionsByKey.values())
      .sort((left, right) => left.label.localeCompare(right.label, undefined, { sensitivity: "base" }));
  };
  const updateCategoryScopeStatus = (filtersWithoutCategories, categoryOptions) => {
    if (!categoryScopeStatusElement) {
      return;
    }
    const selectedCategories = parseStoredMultiselectValues(filterCategoryIdsInput, normalizeCategoryFilterValue);
    if (selectedCategories.length === 0) {
      categoryScopeStatusElement.textContent = "";
      categoryScopeStatusElement.hidden = true;
      categoryScopeStatusElement.classList.remove("warning");
      return;
    }

    const categoryOptionByKey = new Map(categoryOptions.map((option) => [option.key, option]));
    const staleSelections = selectedCategories.filter((item) => {
      const option = categoryOptionByKey.get(item.key);
      return !option || option.count <= 0;
    });
    if (staleSelections.length > 0) {
      const staleLabels = staleSelections.map((item) => item.value).join(", ");
      categoryScopeStatusElement.textContent = (
        `Selected categories currently have no cached matches with other active filters: ${staleLabels}.`
      );
      categoryScopeStatusElement.hidden = false;
      categoryScopeStatusElement.classList.add("warning");
      return;
    }

    const selectedKeys = new Set(selectedCategories.map((item) => item.key));
    let matchingBeforeCategoryCount = 0;
    for (const entry of allEntries) {
      if (!entryMatchesFilters(entry, filtersWithoutCategories)) {
        continue;
      }
      if ((entry.categoryValues || []).some((item) => selectedKeys.has(item))) {
        matchingBeforeCategoryCount += 1;
      }
    }
    const categoryLabel = selectedCategories.length === 1 ? "category" : "categories";
    const resultLabel = matchingBeforeCategoryCount === 1 ? "result" : "results";
    categoryScopeStatusElement.textContent = (
      `${selectedCategories.length} ${categoryLabel} selected; `
      + `${matchingBeforeCategoryCount} cached ${resultLabel} match before category-only narrowing.`
    );
    categoryScopeStatusElement.hidden = false;
    categoryScopeStatusElement.classList.remove("warning");
  };

  const initSearchMultiselect = ({
    storageInput,
    optionsContainer,
    summaryElement,
    selectAllButton,
    clearButton,
    allLabel,
    emptyLabel,
    normalizeValue,
    options,
    onSelectionChange = () => {},
    renderOption = (option) => option.label,
  }) => {
    if (!storageInput || !optionsContainer || !summaryElement) {
      return noOpMultiselectController;
    }
    let currentOptions = Array.isArray(options) ? [...options] : [];

    const readSelectedFromStorage = () => (
      new Map(parseStoredMultiselectValues(storageInput, normalizeValue).map((item) => [item.key, item.value]))
    );

    const updateSummary = (selected) => {
      if (selected.length === 0) {
        summaryElement.textContent = allLabel;
        return;
      }
      if (selected.length <= 2) {
        summaryElement.textContent = selected.map((item) => item.value).join(", ");
        return;
      }
      summaryElement.textContent = `${selected.length} selected`;
    };

    const syncFromUi = ({ notify } = { notify: false }) => {
      const selected = Array.from(optionsContainer.querySelectorAll('input[type="checkbox"]:checked')).map((input) => ({
        value: String(input.value || "").trim(),
        key: String(input.dataset.searchFilterKey || ""),
      }));
      storageInput.value = selected.map((item) => item.value).join(", ");
      updateSummary(selected);
      if (notify) {
        onSelectionChange();
      }
    };

    const render = () => {
      const selectedMap = readSelectedFromStorage();
      const optionsToRender = currentOptions.map((option) => ({ ...option, inactive: false }));
      for (const [key, value] of selectedMap.entries()) {
        if (optionsToRender.some((item) => item.key === key)) {
          continue;
        }
        optionsToRender.push({
          key,
          value,
          label: `${value}`,
          count: 0,
          inactive: true,
        });
      }

      if (optionsToRender.length === 0) {
        optionsContainer.innerHTML = "";
        const emptyElement = document.createElement("p");
        emptyElement.className = "search-multiselect-empty";
        emptyElement.textContent = emptyLabel;
        optionsContainer.appendChild(emptyElement);
        updateSummary(parseStoredMultiselectValues(storageInput, normalizeValue));
        if (selectAllButton) {
          selectAllButton.disabled = true;
        }
        if (clearButton) {
          clearButton.disabled = true;
        }
        return;
      }

      optionsContainer.innerHTML = "";
      const selectedKeys = new Set(selectedMap.keys());
      for (const option of optionsToRender) {
        const optionLabel = document.createElement("label");
        optionLabel.className = "search-multiselect-option";
        if (option.inactive) {
          optionLabel.classList.add("search-multiselect-option--inactive");
        }

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.value = option.value;
        checkbox.dataset.searchFilterKey = option.key;
        checkbox.checked = selectedKeys.has(option.key);
        checkbox.addEventListener("change", () => syncFromUi({ notify: true }));

        const renderedOption = renderOption(option);
        if (Array.isArray(renderedOption)) {
          optionLabel.append(checkbox, ...renderedOption);
        } else if (renderedOption instanceof Node) {
          optionLabel.append(checkbox, renderedOption);
        } else {
          const text = document.createElement("span");
          text.className = "search-multiselect-option-text";
          text.textContent = String(renderedOption ?? option.label);
          optionLabel.append(checkbox, text);
        }
        optionsContainer.appendChild(optionLabel);
      }

      if (selectAllButton) {
        selectAllButton.disabled = false;
      }
      if (clearButton) {
        clearButton.disabled = false;
      }
      syncFromUi({ notify: false });
    };

    if (selectAllButton) {
      selectAllButton.addEventListener("click", (event) => {
        event.preventDefault();
        optionsContainer.querySelectorAll('input[type="checkbox"]').forEach((input) => {
          input.checked = true;
        });
        syncFromUi({ notify: true });
      });
    }
    if (clearButton) {
      clearButton.addEventListener("click", (event) => {
        event.preventDefault();
        optionsContainer.querySelectorAll('input[type="checkbox"]').forEach((input) => {
          input.checked = false;
        });
        syncFromUi({ notify: true });
      });
    }

    render();
    return {
      refreshOptions(nextOptions) {
        currentOptions = Array.isArray(nextOptions) ? [...nextOptions] : [];
        render();
      },
    };
  };

  const indexerMultiselectController = initSearchMultiselect({
    storageInput: filterIndexersInput,
    optionsContainer: indexerMultiSelectOptions,
    summaryElement: indexerMultiSelectSummary,
    selectAllButton: indexerMultiSelectSelectAll,
    clearButton: indexerMultiSelectClear,
    allLabel: "All indexers",
    emptyLabel: "Run a search to populate indexers.",
    normalizeValue: (value) => String(value || "").trim().toLocaleLowerCase(),
    options: buildDistinctIndexerOptions(),
    onSelectionChange: () => applyLocalFilters(),
  });

  const categoryMultiselectController = initSearchMultiselect({
    storageInput: filterCategoryIdsInput,
    optionsContainer: categoryMultiSelectOptions,
    summaryElement: categoryMultiSelectSummary,
    selectAllButton: categoryMultiSelectSelectAll,
    clearButton: categoryMultiSelectClear,
    allLabel: "All categories",
    emptyLabel: "Run a search to populate categories.",
    normalizeValue: normalizeCategoryFilterValue,
    options: buildDistinctCategoryOptions(),
    onSelectionChange: () => applyLocalFilters(),
    renderOption: (option) => {
      const text = document.createElement("span");
      text.className = "search-multiselect-option-text";
      text.textContent = option.label;
      if (typeof option.count !== "number") {
        return text;
      }
      const countBadge = document.createElement("span");
      countBadge.className = "search-multiselect-option-count";
      countBadge.textContent = option.inactive ? "inactive" : String(option.count);
      return [text, countBadge];
    },
  });

  const applyViewMode = () => {
    const tableMode = controlState.viewMode === "table";
    for (const section of sections) {
      const state = sectionState[section];
      if (!state) {
        continue;
      }
      if (state.cardContainer) {
        state.cardContainer.hidden = tableMode;
      }
      if (state.tableWrap) {
        state.tableWrap.hidden = !tableMode;
      }
    }
  };

  const applyFiltersForSection = (section, filters, sortCriteria) => {
    const state = sectionState[section];
    if (!state) {
      return { visibleEntries: [], hiddenEntries: [] };
    }

    const sortedEntries = [...state.entries].sort((left, right) => compareEntries(left, right, sortCriteria, filters));
    if (state.cardContainer) {
      for (const entry of sortedEntries) {
        state.cardContainer.appendChild(entry.card);
      }
    }
    if (state.tableBody) {
      for (const entry of sortedEntries) {
        if (entry.row) {
          state.tableBody.appendChild(entry.row);
        }
      }
    }

    const visibleEntries = [];
    const hiddenEntries = [];
    let visibleCount = 0;
    for (const entry of sortedEntries) {
      const failure = entryFilterFailure(entry, filters);
      const visible = failure === null;
      const effectiveSource = effectiveQuerySourcePresentation(entry, filters);
      entry.card.dataset.querySourceKey = effectiveSource.key;
      entry.card.dataset.querySource = effectiveSource.label;
      if (entry.row) {
        entry.row.dataset.querySourceKey = effectiveSource.key;
        entry.row.dataset.querySource = effectiveSource.label;
      }
      if (entry.cardQuerySourceChipElement) {
        entry.cardQuerySourceChipElement.textContent = effectiveSource.label;
      }
      if (entry.cardQuerySourceDetailElement) {
        entry.cardQuerySourceDetailElement.textContent = effectiveSource.label;
      }
      if (entry.rowQuerySourceElement) {
        entry.rowQuerySourceElement.textContent = effectiveSource.label;
      }
      entry.card.hidden = !visible;
      if (entry.row) {
        entry.row.hidden = !(visible || controlState.showHiddenRows);
        entry.row.classList.toggle("search-row-filter-blocked", !visible);
      }
      if (entry.visibilityStatusElement) {
        entry.visibilityStatusElement.dataset.state = visible ? "visible" : "hidden";
        entry.visibilityStatusElement.textContent = visible ? "Visible" : failure;
      }
      if (visible) {
        visibleCount += 1;
        visibleEntries.push(entry);
      } else {
        hiddenEntries.push(entry);
      }
    }

    if (state.filteredCountElement) {
      state.filteredCountElement.textContent = String(visibleCount);
    }
    if (state.fetchedCountElement) {
      state.fetchedCountElement.textContent = String(state.entries.length);
    }
    if (state.scopeSummaryElement) {
      const scopeSummary = searchScopeSummaryText(filters);
      state.scopeSummaryElement.textContent = scopeSummary;
      state.scopeSummaryElement.hidden = scopeSummary.length === 0;
    }
    if (state.hiddenSummaryElement) {
      if (hiddenEntries.length > 0) {
        const actionLabel = controlState.showHiddenRows
          ? "Hidden rows are shown below with their first blocker."
          : "Enable \"Show hidden fetched rows\" to inspect them in the table.";
        const rowLabel = hiddenEntries.length === 1 ? "row is" : "rows are";
        state.hiddenSummaryElement.textContent = (
          `${hiddenEntries.length} fetched row${hiddenEntries.length === 1 ? "" : "s"} `
          + `${rowLabel} currently hidden. ${actionLabel}`
        );
        state.hiddenSummaryElement.hidden = false;
      } else {
        state.hiddenSummaryElement.textContent = "";
        state.hiddenSummaryElement.hidden = true;
      }
    }
    if (state.emptyState) {
      state.emptyState.hidden = visibleCount > 0;
    }
    return { visibleEntries, hiddenEntries };
  };

  const updateSourceBreakdownCounts = (visibleCombinedEntries) => {
    if (sourceSummaryState.length === 0) {
      return;
    }
    const visibleBySource = new Map();
    for (const source of sourceSummaryState) {
      if (source.key === "combined") {
        visibleBySource.set(source.key, visibleCombinedEntries.length);
        continue;
      }
      visibleBySource.set(source.key, 0);
    }
    const filters = getActiveFilters();
    for (const entry of visibleCombinedEntries) {
      for (const sourceKey of effectiveQuerySourceKeys(entry, filters)) {
        if (!visibleBySource.has(sourceKey)) {
          continue;
        }
        visibleBySource.set(sourceKey, Number(visibleBySource.get(sourceKey) || 0) + 1);
      }
    }
    for (const source of sourceSummaryState) {
      if (source.filteredCountElement) {
        source.filteredCountElement.textContent = String(visibleBySource.get(source.key) || 0);
      }
      if (source.fetchedCountElement) {
        source.fetchedCountElement.textContent = String(source.fetchedCount);
      }
    }
  };

  applyLocalFilters = () => {
    refreshSearchPatternPreview();
    let filters = getActiveFilters();
    const filtersWithoutCategories = cloneFilters(filters);
    filtersWithoutCategories.categories = [];
    const scopedCategoryOptions = buildCategoryOptionsForFilters(filtersWithoutCategories);
    categoryMultiselectController.refreshOptions(scopedCategoryOptions);
    updateCategoryScopeStatus(filtersWithoutCategories, scopedCategoryOptions);
    indexerMultiselectController.refreshOptions(buildDistinctIndexerOptions());
    filters = getActiveFilters();
    const sortCriteria = getSortCriteria();
    applyViewMode();
    let visibleCombinedEntries = [];
    for (const section of sections) {
      const { visibleEntries } = applyFiltersForSection(section, filters, sortCriteria);
      if (section === "combined") {
        visibleCombinedEntries = visibleEntries;
      }
    }
    updateSourceBreakdownCounts(visibleCombinedEntries);
    renderActiveFilterChips(filters);
  };

  const localFilterInputs = [
    includeReleaseYearInput,
    releaseYearInput,
    keywordsAllInput,
    keywordsAnyInput,
    keywordsNotInput,
    mustContainOverrideInput,
    generatedPatternInput,
    startSeasonInput,
    startEpisodeInput,
    sizeMinInput,
    sizeMaxInput,
    filterIndexersInput,
    filterCategoryIdsInput,
    mediaTypeInput,
  ].filter(Boolean);

  for (const input of localFilterInputs) {
    input.addEventListener("input", applyLocalFilters);
    input.addEventListener("change", applyLocalFilters);
  }

  form.querySelector("#feed-options")?.addEventListener("change", (event) => {
    if (!(event.target instanceof HTMLInputElement)) {
      return;
    }
    if (event.target.name !== "feed_urls") {
      return;
    }
    applyLocalFilters();
  });

  if (queryInput) {
    const refreshAndApplyLocalFilters = () => {
      refreshSearchPatternPreview();
      applyLocalFilters();
    };
    queryInput.addEventListener("input", refreshAndApplyLocalFilters);
    queryInput.addEventListener("change", refreshAndApplyLocalFilters);
  }

  if (mediaTypeInput) {
    mediaTypeInput.addEventListener("change", () => {
      syncSearchQualityVisibility();
      applyLocalFilters();
    });
  }
  if (includeReleaseYearInput) {
    includeReleaseYearInput.addEventListener("change", () => {
      syncReleaseYearFieldState();
      applyLocalFilters();
    });
  }

  const qualityTokenControls = initUnifiedQualityTokenControls(form, { onChange: applyLocalFilters });

  for (const button of sortHeaderButtons) {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      updateSortFromHeader(button.dataset.searchTableSortField || "", event.shiftKey);
    });
  }

  for (const controlSet of controlSets) {
    if (controlSet.viewModeSelect) {
      const syncViewMode = () => {
        controlState = {
          ...controlState,
          viewMode: normalizeViewMode(controlSet.viewModeSelect?.value || controlState.viewMode),
        };
        syncControlSets(controlSet);
        applyLocalFilters();
      };
      controlSet.viewModeSelect.addEventListener("change", syncViewMode);
      controlSet.viewModeSelect.addEventListener("input", syncViewMode);
    }
    if (controlSet.showHiddenToggle) {
      controlSet.showHiddenToggle.addEventListener("change", () => {
        controlState = {
          ...controlState,
          showHiddenRows: Boolean(controlSet.showHiddenToggle?.checked),
        };
        syncControlSets(controlSet);
        applyLocalFilters();
      });
    }
    if (controlSet.clearFiltersButton) {
      controlSet.clearFiltersButton.addEventListener("click", (event) => {
        event.preventDefault();
        clearLocalFilters();
        qualityTokenControls.syncFromStateInputs();
        applyLocalFilters();
      });
    }
    if (controlSet.saveDefaultsButton) {
      controlSet.saveDefaultsButton.addEventListener("click", async () => {
        for (const button of saveDefaultsButtons) {
          button.disabled = true;
        }
        setSaveDefaultStatus("Saving search view defaults...");
        try {
          const response = await fetch("/api/search/preferences", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              view_mode: controlState.viewMode,
              sort_criteria: controlState.sortCriteria,
              ...readQueueDefaultsForSave(),
            }),
          });
          const payload = await response.json();
          if (!response.ok) {
            const errorMessage = String(payload?.error || "Could not save search view defaults.");
            throw new Error(errorMessage);
          }
          setSaveDefaultStatus("Saved. New searches will use this view, sort order, and queue options.");
        } catch (error) {
          const message = error instanceof Error ? error.message : "Could not save search view defaults.";
          setSaveDefaultStatus(message, true);
        } finally {
          for (const button of saveDefaultsButtons) {
            button.disabled = false;
          }
        }
      });
    }
  }

  syncSearchQualityVisibility();
  syncReleaseYearFieldState();
  syncControlSets();
  applyLocalFilters();
}

function initResultQueueActions(root = document) {
  const queueButtons = Array.from(root.querySelectorAll("[data-result-queue-button]"));
  if (queueButtons.length === 0) {
    return;
  }

  const queueOptionContainers = Array.from(root.querySelectorAll("[data-result-queue-options]"));
  const statusElements = Array.from(root.querySelectorAll("[data-result-queue-status]"));

  const resolveQueueOptionContainer = (button) => {
    const localScope = button.closest("[data-search-page], #inline-search-results");
    if (localScope) {
      const scopedContainer = localScope.querySelector("[data-result-queue-options]");
      if (scopedContainer) {
        return scopedContainer;
      }
    }
    return queueOptionContainers[0] || null;
  };

  const resolveStatusTargets = (button) => {
    const container = resolveQueueOptionContainer(button);
    if (container) {
      const scopedStatus = Array.from(container.querySelectorAll("[data-result-queue-status]"));
      if (scopedStatus.length > 0) {
        return scopedStatus;
      }
    }
    return statusElements;
  };

  const setQueueStatus = (button, message, isError = false) => {
    for (const statusElement of resolveStatusTargets(button)) {
      statusElement.textContent = message;
      statusElement.style.color = isError ? "var(--danger)" : "";
    }
  };

  const readQueueOptions = (button) => {
    const optionsContainer = resolveQueueOptionContainer(button);
    const pausedInput = optionsContainer?.querySelector('[data-result-queue-option="paused"]');
    const sequentialInput = optionsContainer?.querySelector('[data-result-queue-option="sequential"]');
    const firstLastInput = optionsContainer?.querySelector('[data-result-queue-option="first_last_piece_prio"]');
    return {
      addPaused: pausedInput ? Boolean(pausedInput.checked) : true,
      sequentialDownload: Boolean(sequentialInput?.checked),
      firstLastPiecePrio: Boolean(firstLastInput?.checked),
    };
  };

  for (const button of queueButtons) {
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      const resultLink = String(button.dataset.resultLink || "").trim();
      if (!resultLink) {
        setQueueStatus(button, "Could not queue: missing result link.", true);
        return;
      }
      const groupedLinks = parseJsonData(button.dataset.resultLinks || "[]", []);
      const trackerUrls = parseJsonData(button.dataset.resultTrackerUrls || "[]", []);
      const resultInfoHash = String(button.dataset.resultInfoHash || "").trim().toLowerCase();
      const ruleId = String(button.dataset.resultRuleId || "").trim();
      const queueOptions = readQueueOptions(button);
      const originalLabel = button.textContent;
      button.disabled = true;
      button.textContent = "Queueing...";
      const queueingLabel = Array.isArray(groupedLinks) && groupedLinks.length > 1
        ? "Queueing grouped same-hash results in qBittorrent..."
        : "Queueing result in qBittorrent...";
      setQueueStatus(button, queueingLabel);

      try {
        const response = await fetch("/api/search/queue", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            link: resultLink,
            links: Array.isArray(groupedLinks) && groupedLinks.length > 0 ? groupedLinks : [resultLink],
            info_hash: resultInfoHash || null,
            tracker_urls: Array.isArray(trackerUrls) ? trackerUrls : [],
            rule_id: ruleId || null,
            add_paused: queueOptions.addPaused,
            sequential_download: queueOptions.sequentialDownload,
            first_last_piece_prio: queueOptions.firstLastPiecePrio,
          }),
        });
        let payload = {};
        try {
          payload = await response.json();
        } catch {
          payload = {};
        }
        if (!response.ok) {
          const errorMessage = String(payload?.error || "Could not queue this result.");
          throw new Error(errorMessage);
        }
        const queueSummary = [
          "Queued in qBittorrent.",
          payload?.message ? String(payload.message) : "",
          payload?.category ? `Category: ${payload.category}.` : "",
          payload?.save_path ? `Save path: ${payload.save_path}.` : "",
        ]
          .filter(Boolean)
          .join(" ");
        setQueueStatus(button, queueSummary);
      } catch (error) {
        const message = error instanceof Error ? error.message : "Could not queue this result.";
        setQueueStatus(button, message, true);
      } finally {
        button.disabled = false;
        button.textContent = originalLabel;
      }
    });
  }
}

function initRuleForm(form) {
  const qualityOptions = parseJsonData(form.dataset.qualityOptions, []);
  const qualityPatternMap = buildQualityPatternMap(qualityOptions);
  const qualityTokenGroupMap = buildQualityTokenGroupMapFromElements(form);
  const qualityMediaTypeMap = Object.fromEntries(
    qualityOptions.filter((option) => option?.value).map((option) => [
      option.value,
      normalizeMediaTypes(option.media_types),
    ])
  );
  const qualityOptionOrder = Object.fromEntries(
    qualityOptions.filter((option) => option?.value).map((option, index) => [option.value, index])
  );
  let availableFilterProfiles = parseJsonData(form.dataset.availableFilterProfiles, []);
  let availableFilterProfileMap = buildFilterProfileMap(availableFilterProfiles);
  const metadataProviders = parseJsonData(form.dataset.metadataProviders, []);
  const metadataLookupDisabled = form.dataset.metadataDisabled === "true";
  const categoryInput = form.querySelector('input[name="assigned_category"]');
  const savePathInput = form.querySelector('input[name="save_path"]');
  const patternPreview = form.querySelector("#pattern-preview");
  const metadataProviderSelect = form.querySelector("#metadata-lookup-provider");
  const metadataLookupValueInput = form.querySelector("#metadata-lookup-value");
  const metadataButton = form.querySelector("#metadata-lookup");
    const feedRefreshButton = form.querySelector("#feed-refresh");
    const feedSelectAllButton = form.querySelector("#feed-select-all");
    const feedClearAllButton = form.querySelector("#feed-clear-all");
    const feedOptionsContainer = form.querySelector("#feed-options");
    const languageSelect = form.querySelector("#rule-language-select");
    const feedModeHelper = form.querySelector("[data-feed-mode-helper]");
    const mediaField = form.querySelector('select[name="media_type"]');
  const qualityProfileInput = form.querySelector('input[name="quality_profile"]');
  const filterProfileSelect = form.querySelector("#filter-profile-select");
  const saveNewProfileButton = form.querySelector("#filter-profile-save-new");
  const overwriteProfileButton = form.querySelector("#filter-profile-overwrite");
  const releaseYearInput = form.querySelector('input[name="release_year"]');
  const imdbFieldWrapper = form.querySelector("[data-imdb-field]");
  const runSearchHereLink = document.querySelector("[data-run-search-here]");

  let categoryTouched = Boolean(categoryInput?.value.trim());
  let savePathTouched = Boolean(savePathInput?.value.trim());
  let releaseYearTouched = Boolean(releaseYearInput?.value.trim());
  let currentMediaType = mediaField?.value || "series";

  const feedEmptyMessage = feedOptionsContainer?.dataset.emptyMessage || "No feeds available yet.";
  const parseElementMediaTypes = (element) => normalizeMediaTypes((element?.dataset?.mediaTypes || "").split(","));
  const getCurrentMediaType = () => mediaField?.value || currentMediaType || "series";

  const getFeedCheckboxes = () => Array.from(feedOptionsContainer?.querySelectorAll('input[name="feed_urls"]') || []);
  const initialFeedUrls = parseJsonData(form.dataset.initialFeedUrls || "[]", []);
  const normalizeFeedUrlList = (values) => {
    const normalized = [];
    const seen = new Set();
    for (const value of Array.isArray(values) ? values : []) {
      const candidate = String(value || "").trim();
      if (!candidate || seen.has(candidate)) {
        continue;
      }
      seen.add(candidate);
      normalized.push(candidate);
    }
    return normalized.sort((left, right) => left.localeCompare(right, undefined, { sensitivity: "base" }));
  };
  const selectedFeedUrls = () => (
    getFeedCheckboxes()
      .filter((checkbox) => checkbox.checked)
      .map((checkbox) => checkbox.value)
  );
  const feedsDifferFromInitialSelection = () => {
    const initial = normalizeFeedUrlList(initialFeedUrls);
    const selected = normalizeFeedUrlList(selectedFeedUrls());
    if (initial.length !== selected.length) {
      return true;
    }
    for (let index = 0; index < initial.length; index += 1) {
      if (initial[index] !== selected[index]) {
        return true;
      }
    }
    return false;
  };

  const buildFeedLabelMap = () => {
    const labels = new Map();
    if (!feedOptionsContainer) {
      return labels;
    }
    feedOptionsContainer.querySelectorAll("[data-feed-option]").forEach((option) => {
      const url = option.dataset.feedUrl || "";
      if (!url || labels.has(url)) {
        return;
      }
      labels.set(url, option.dataset.feedLabel || url);
    });
    return labels;
  };

  const renderFeedOptions = (feeds, selectedUrls = []) => {
    if (!feedOptionsContainer) {
      return;
    }

    const selected = new Set(selectedUrls || []);
    const seenUrls = new Set();
    feedOptionsContainer.innerHTML = "";

    for (const feed of feeds || []) {
      const url = feed?.url || "";
      if (!url || seenUrls.has(url)) {
        continue;
      }
      seenUrls.add(url);

      const option = document.createElement("label");
      option.className = "feed-option";
      option.dataset.feedOption = "true";
      option.dataset.feedUrl = url;
      option.dataset.feedLabel = feed.label || url;

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.name = "feed_urls";
      checkbox.value = url;
      checkbox.checked = selected.has(url);

      const label = document.createElement("span");
      label.className = "feed-option-label";
      label.textContent = feed.label || url;

      option.append(checkbox, label);
      feedOptionsContainer.appendChild(option);
    }

    if (feedOptionsContainer.childElementCount > 0) {
      return;
    }

    const emptyState = document.createElement("p");
    emptyState.className = "feed-empty-state";
    emptyState.textContent = feedEmptyMessage;
    feedOptionsContainer.appendChild(emptyState);
  };

  const syncFeedLanguageMode = () => {
    const languageManaged = Boolean(languageSelect?.value.trim());
    if (feedOptionsContainer) {
      feedOptionsContainer.dataset.languageManaged = languageManaged ? "true" : "false";
    }
    if (feedModeHelper) {
      feedModeHelper.textContent = languageManaged
        ? "Feed selection is currently resolved automatically from the selected language. Clear Language to edit feeds manually."
        : "Choose one or more RSS feeds for this rule. Active Jackett search stays separate and does not populate this list.";
    }
    for (const button of [feedRefreshButton, feedSelectAllButton, feedClearAllButton]) {
      if (button) {
        button.disabled = languageManaged;
      }
    }
    for (const checkbox of getFeedCheckboxes()) {
      checkbox.disabled = languageManaged;
    }
  };

  const normalizeTokenSelection = (includeTokens, excludeTokens) => {
    const normalizedIncludeTokens = [];
    const includeSet = new Set();
    for (const token of includeTokens || []) {
      if (!token || includeSet.has(token)) {
        continue;
      }
      includeSet.add(token);
      normalizedIncludeTokens.push(token);
    }
    const normalizedExcludeTokens = [];
    const excludeSet = new Set();
    for (const token of excludeTokens || []) {
      if (!token || includeSet.has(token) || excludeSet.has(token)) {
        continue;
      }
      excludeSet.add(token);
      normalizedExcludeTokens.push(token);
    }
    normalizedIncludeTokens.sort(
      (left, right) => (qualityOptionOrder[left] ?? Number.MAX_SAFE_INTEGER) - (qualityOptionOrder[right] ?? Number.MAX_SAFE_INTEGER)
    );
    normalizedExcludeTokens.sort(
      (left, right) => (qualityOptionOrder[left] ?? Number.MAX_SAFE_INTEGER) - (qualityOptionOrder[right] ?? Number.MAX_SAFE_INTEGER)
    );
    return {
      include_tokens: normalizedIncludeTokens,
      exclude_tokens: normalizedExcludeTokens,
    };
  };

  const buildCurrentProfilePayload = () => {
    const includeTokens = getCheckedValues(form, "quality_include_tokens");
    return normalizeTokenSelection(includeTokens, getCheckedValues(form, "quality_exclude_tokens"));
  };

  const getProfilesForMediaType = (mediaType) => (
    availableFilterProfiles.filter((profile) => mediaTypeMatchesScope(mediaType, profile.media_types))
  );

  const detectMatchingFilterProfileKey = (mediaType = getCurrentMediaType()) => {
    const currentProfile = buildCurrentProfilePayload();
    for (const profile of getProfilesForMediaType(mediaType)) {
      const candidateProfile = normalizeTokenSelection(
        profile.include_tokens || [],
        profile.exclude_tokens || []
      );
      if (
        orderedValuesMatch(currentProfile.include_tokens, candidateProfile.include_tokens) &&
        orderedValuesMatch(currentProfile.exclude_tokens, candidateProfile.exclude_tokens)
      ) {
        return profile.key;
      }
    }
    return "";
  };

  const syncQualityProfileValue = () => {
    if (!qualityProfileInput) {
      return;
    }
    const matchingProfile = availableFilterProfileMap[detectMatchingFilterProfileKey(getCurrentMediaType())];
    if (matchingProfile?.quality_profile_value) {
      qualityProfileInput.value = matchingProfile.quality_profile_value;
      return;
    }
    const currentProfile = buildCurrentProfilePayload();
    if (!currentProfile.include_tokens.length && !currentProfile.exclude_tokens.length) {
      qualityProfileInput.value = "plain";
      return;
    }
    qualityProfileInput.value = "custom";
  };

  const applyFilterProfile = (profileKey) => {
    const profile = availableFilterProfileMap[profileKey];
    if (!profile) {
      return;
    }
    const includeTokens = profile.include_tokens || [];
    const includeSet = new Set(includeTokens);
    const excludeTokens = (profile.exclude_tokens || []).filter((token) => !includeSet.has(token));
    setCheckedValues(form, "quality_include_tokens", includeTokens);
    setCheckedValues(form, "quality_exclude_tokens", excludeTokens);
    if (filterProfileSelect) {
      filterProfileSelect.value = profileKey;
    }
    qualityTokenControls.syncFromStateInputs({ notify: true });
  };

  const rebuildFilterProfileSelect = (selectedKey, mediaType = getCurrentMediaType()) => {
    if (!filterProfileSelect) {
      return;
    }
    const visibleProfiles = getProfilesForMediaType(mediaType);
    filterProfileSelect.innerHTML = "";
    const blankOption = document.createElement("option");
    blankOption.value = "";
    blankOption.textContent = "Current manual selection";
    filterProfileSelect.appendChild(blankOption);
    let hasSelectedKey = false;
    for (const profile of visibleProfiles) {
      const option = document.createElement("option");
      option.value = profile.key;
      option.textContent = profile.label;
      option.selected = profile.key === selectedKey;
      hasSelectedKey ||= profile.key === selectedKey;
      filterProfileSelect.appendChild(option);
    }
    if (!selectedKey || !hasSelectedKey) {
      filterProfileSelect.value = "";
    }
  };

  const getMetadataProvidersForMediaType = (mediaType) => (
    metadataProviders.filter((provider) => mediaTypeMatchesScope(mediaType, provider.media_types))
  );

  const updateMetadataLookupPlaceholder = (mediaType) => {
    if (!metadataLookupValueInput) {
      return;
    }
    if (mediaType === "music") {
      metadataLookupValueInput.placeholder = "Album title or MusicBrainz ID";
      return;
    }
    if (mediaType === "audiobook") {
      metadataLookupValueInput.placeholder = "Book title, ISBN, or OpenLibrary ID";
      return;
    }
    metadataLookupValueInput.placeholder = "Title or source ID";
  };

  const rebuildMetadataProviderSelect = (mediaType = getCurrentMediaType()) => {
    if (!metadataProviderSelect) {
      return;
    }
    const visibleProviders = getMetadataProvidersForMediaType(mediaType);
    const currentValue = metadataProviderSelect.value;
    metadataProviderSelect.innerHTML = "";
    for (const provider of visibleProviders) {
      const option = document.createElement("option");
      option.value = provider.value;
      option.textContent = provider.label;
      option.selected = provider.value === currentValue;
      metadataProviderSelect.appendChild(option);
    }
    if (visibleProviders.length === 0) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No provider";
      metadataProviderSelect.appendChild(option);
      metadataProviderSelect.value = "";
    } else if (!visibleProviders.some((provider) => provider.value === currentValue)) {
      metadataProviderSelect.value = visibleProviders[0].value;
    }
    updateMetadataLookupPlaceholder(mediaType);
  };

  const persistProfile = async (payload) => {
    const response = await fetch("/api/filter-profiles", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    const body = await response.json();
    if (!response.ok) {
      window.alert(body.error || "Unable to save the profile.");
      return;
    }
    availableFilterProfiles = body.profiles || [];
    availableFilterProfileMap = buildFilterProfileMap(availableFilterProfiles);
    rebuildFilterProfileSelect(body.profile_key || "", getCurrentMediaType());
    syncQualityProfileValue();
  };

  const getIncompatibleTokensForMediaType = (mediaType) => {
    if (mediaType === "other") {
      return [];
    }
    const incompatible = new Set();
    for (const input of form.querySelectorAll('input[name="quality_include_tokens"], input[name="quality_exclude_tokens"]')) {
      if (!input.checked && !input.defaultChecked) {
        continue;
      }
      if (!input.checked) {
        continue;
      }
      if (!mediaTypeMatchesScope(mediaType, qualityMediaTypeMap[input.value])) {
        incompatible.add(input.value);
      }
    }
    return Array.from(incompatible);
  };

  const clearIncompatibleTokens = (tokens) => {
    const incompatible = new Set(tokens || []);
    if (incompatible.size === 0) {
      return;
    }
    form.querySelectorAll('input[name="quality_include_tokens"], input[name="quality_exclude_tokens"]').forEach((input) => {
      if (incompatible.has(input.value)) {
        input.checked = false;
      }
    });
    qualityTokenControls.syncFromStateInputs();
  };

  const applyQualityVisibility = (mediaType) => {
    form.querySelectorAll("[data-quality-option]").forEach((optionLabel) => {
      const optionVisible = mediaTypeMatchesScope(mediaType, parseElementMediaTypes(optionLabel));
      optionLabel.hidden = !optionVisible;
      optionLabel.querySelectorAll('input[name="quality_include_tokens"], input[name="quality_exclude_tokens"]').forEach((input) => {
        input.disabled = !optionVisible;
      });
      if (!optionVisible) {
        setQualityTokenSliderMode(optionLabel, "off", true);
      }
    });

    form.querySelectorAll("[data-quality-group]").forEach((group) => {
      const groupMatches = mediaTypeMatchesScope(mediaType, parseElementMediaTypes(group));
      const visibleOptions = Array.from(group.querySelectorAll("[data-quality-option]")).some((option) => !option.hidden);
      group.hidden = !groupMatches || !visibleOptions;
    });
    qualityTokenControls.syncFromStateInputs();
  };

  const applyMediaTypeVisibility = (mediaType) => {
    currentMediaType = mediaType || "series";
    applyQualityVisibility(currentMediaType);
    rebuildFilterProfileSelect(filterProfileSelect?.value || "", currentMediaType);
    rebuildMetadataProviderSelect(currentMediaType);
    if (imdbFieldWrapper) {
      imdbFieldWrapper.hidden = currentMediaType === "music" || currentMediaType === "audiobook";
    }
  };

  const handleMediaTypeSelectionChange = (nextMediaType) => {
    const previousMediaType = currentMediaType;
    if (!nextMediaType || nextMediaType === previousMediaType) {
      applyMediaTypeVisibility(getCurrentMediaType());
      refreshDerivedFields();
      return;
    }

    const selectedProfileKey = filterProfileSelect?.value || "";
    const selectedProfile = availableFilterProfileMap[selectedProfileKey];
    const incompatibleTokens = getIncompatibleTokensForMediaType(nextMediaType);
    const incompatibleProfileKey = (
      nextMediaType !== "other"
      && selectedProfileKey
      && selectedProfile
      && !mediaTypeMatchesScope(nextMediaType, selectedProfile.media_types)
    )
      ? selectedProfileKey
      : "";

    if (nextMediaType !== "other" && (incompatibleTokens.length > 0 || incompatibleProfileKey)) {
      const confirmed = window.confirm(
        "Switching media type will clear filters or presets that do not apply to the new media type. Continue?"
      );
      if (!confirmed) {
        if (mediaField) {
          mediaField.value = previousMediaType;
        }
        return;
      }
      clearIncompatibleTokens(incompatibleTokens);
      if (incompatibleProfileKey && filterProfileSelect) {
        filterProfileSelect.value = "";
      }
    }

    applyMediaTypeVisibility(nextMediaType);
    syncQualityProfileValue();
    refreshDerivedFields();
  };

  const refreshDerivedFields = () => {
    if (categoryInput && !categoryTouched) {
      categoryInput.value = deriveCategory(form);
    }
    if (savePathInput && !savePathTouched) {
      savePathInput.value = deriveSavePath(form);
    }
    if (patternPreview) {
      const nextPattern = derivePattern(form, qualityPatternMap, qualityTokenGroupMap);
      if (patternPreview.value !== nextPattern) {
        patternPreview.value = nextPattern;
        patternPreview.dispatchEvent(new Event("input", { bubbles: true }));
      }
    }
  };

  categoryInput?.addEventListener("input", () => {
    categoryTouched = true;
  });
  savePathInput?.addEventListener("input", () => {
    savePathTouched = true;
  });
  releaseYearInput?.addEventListener("input", () => {
    releaseYearTouched = true;
  });

  const qualityTokenControls = initUnifiedQualityTokenControls(form, {
    onChange: () => {
      syncQualityProfileValue();
      refreshDerivedFields();
    },
  });
  mediaField?.addEventListener("change", () => {
    handleMediaTypeSelectionChange(mediaField.value);
  });
  const handleFilterProfileSelection = () => {
    const selectedKey = filterProfileSelect?.value || "";
    if (!selectedKey) {
      syncQualityProfileValue();
      refreshDerivedFields();
      return;
    }
    applyFilterProfile(selectedKey);
  };
  filterProfileSelect?.addEventListener("input", handleFilterProfileSelection);
  filterProfileSelect?.addEventListener("change", handleFilterProfileSelection);
  saveNewProfileButton?.addEventListener("click", async () => {
    const profileName = window.prompt("New profile name");
    if (!profileName || !profileName.trim()) {
      return;
    }
    await persistProfile({
      mode: "create",
      profile_name: profileName.trim(),
      media_type: getCurrentMediaType(),
      ...buildCurrentProfilePayload(),
    });
  });
  overwriteProfileButton?.addEventListener("click", async () => {
    const selectedKey = filterProfileSelect?.value || "";
    const selectedProfile = availableFilterProfileMap[selectedKey];
    if (!selectedKey || !selectedProfile) {
      window.alert("Select a filter profile to overwrite.");
      return;
    }
    await persistProfile({
      mode: "overwrite",
      target_key: selectedKey,
      media_type: getCurrentMediaType(),
      ...buildCurrentProfilePayload(),
    });
  });

  form.querySelectorAll('input, select, textarea').forEach((element) => {
    if (element === filterProfileSelect) {
      return;
    }
    element.addEventListener("input", refreshDerivedFields);
    element.addEventListener("change", refreshDerivedFields);
  });

  metadataButton?.addEventListener("click", async () => {
    if (metadataLookupDisabled) {
      window.alert("Metadata lookup is disabled in Settings.");
      return;
    }
    if (!metadataLookupValueInput || !metadataLookupValueInput.value.trim()) {
      window.alert("Enter a title or source ID first.");
      return;
    }

    const response = await fetch("/api/metadata/lookup", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        provider: metadataProviderSelect?.value || "omdb",
        lookup_value: metadataLookupValueInput.value.trim(),
        media_type: getCurrentMediaType(),
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      window.alert(payload.error || "Metadata lookup failed.");
      return;
    }

    const titleField = form.querySelector('input[name="normalized_title"]');
    const contentField = form.querySelector('input[name="content_name"]');
    const ruleNameField = form.querySelector('input[name="rule_name"]');
    const imdbField = form.querySelector('input[name="imdb_id"]');
    const posterField = form.querySelector('input[name="poster_url"]');

    if (titleField) {
      titleField.value = payload.title || "";
    }
    if (contentField && !contentField.value.trim()) {
      contentField.value = payload.title || "";
    }
    if (ruleNameField && !ruleNameField.value.trim()) {
      ruleNameField.value = payload.title || "";
    }
    if (mediaField && payload.media_type) {
      mediaField.value = payload.media_type;
      handleMediaTypeSelectionChange(payload.media_type);
    }
    if (imdbField && payload.imdb_id) {
      imdbField.value = payload.imdb_id;
    }
    if (posterField) {
      posterField.value = payload.poster_url || "";
    }
    if (releaseYearInput && (!releaseYearTouched || !releaseYearInput.value.trim())) {
      releaseYearInput.value = normalizeReleaseYear(payload.year || "");
      releaseYearTouched = Boolean(releaseYearInput.value.trim());
    }

    categoryTouched = false;
    savePathTouched = false;
    refreshDerivedFields();
  });


  const notifyFeedSelectionChanged = () => {
    const firstCheckbox = getFeedCheckboxes()[0];
    if (!firstCheckbox) {
      return;
    }
    firstCheckbox.dispatchEvent(new Event("change", { bubbles: true }));
  };

  feedSelectAllButton?.addEventListener("click", () => {
    getFeedCheckboxes().forEach((checkbox) => {
      checkbox.checked = true;
    });
    notifyFeedSelectionChanged();
  });

  feedClearAllButton?.addEventListener("click", () => {
    getFeedCheckboxes().forEach((checkbox) => {
      checkbox.checked = false;
    });
    notifyFeedSelectionChanged();
  });

  feedRefreshButton?.addEventListener("click", async () => {
    const response = await fetch("/api/feeds/refresh", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) {
      window.alert(payload.error || "Feed refresh failed.");
      return;
    }
    if (!feedOptionsContainer) {
      return;
    }

    const selectedUrls = getFeedCheckboxes()
      .filter((checkbox) => checkbox.checked)
      .map((checkbox) => checkbox.value);
    const existingLabels = buildFeedLabelMap();
    const mergedFeeds = [];
    const seenUrls = new Set();

    for (const feed of payload.feeds || []) {
      const url = feed?.url || "";
      if (!url || seenUrls.has(url)) {
        continue;
      }
      seenUrls.add(url);
      mergedFeeds.push({ url, label: feed.label || url });
    }

    for (const url of selectedUrls) {
      if (!url || seenUrls.has(url)) {
        continue;
      }
      seenUrls.add(url);
      mergedFeeds.push({ url, label: existingLabels.get(url) || `Saved feed: ${url}` });
    }

    renderFeedOptions(mergedFeeds, selectedUrls);
    syncFeedLanguageMode();
  });

  languageSelect?.addEventListener("change", () => {
    syncFeedLanguageMode();
    notifyFeedSelectionChanged();
  });

  runSearchHereLink?.addEventListener("click", (event) => {
    event.preventDefault();
    const href = runSearchHereLink.getAttribute("href") || "";
    if (!href) {
      return;
    }
    const url = new URL(href, window.location.origin);
    if (feedsDifferFromInitialSelection()) {
      url.searchParams.set("feed_scope_override", "1");
      for (const feedUrl of selectedFeedUrls()) {
        url.searchParams.append("feed_urls", feedUrl);
      }
    } else {
      url.searchParams.delete("feed_scope_override");
      url.searchParams.delete("feed_urls");
    }
    window.location.href = `${url.pathname}${url.search}${url.hash}`;
  });

  applyMediaTypeVisibility(currentMediaType);
  syncQualityProfileValue();
  refreshDerivedFields();
  syncFeedLanguageMode();
}

function initSettingsForm(form) {
  bindExclusiveQualitySelections(
    form,
    "profile_1080p_include_tokens",
    "profile_1080p_exclude_tokens"
  );
  bindExclusiveQualitySelections(
    form,
    "profile_2160p_hdr_include_tokens",
    "profile_2160p_hdr_exclude_tokens"
  );
}

function initRulesPage(container) {
  const FILTER_STORAGE_KEY = "qb-rules-page-filters:v1";
  const FILTER_RESTORE_FLAG_KEY = "qb-rules-page-filters:restoring";
  const FILTER_FIELD_NAMES = ["search", "media", "sync", "enabled", "release", "exact"];
  const filterForm = container.querySelector("[data-rules-filter-form]");
  const tableWrap = container.querySelector("[data-rules-table-wrap]");
  const cardsWrap = container.querySelector("[data-rules-cards-wrap]");
  const tableBody = container.querySelector("[data-rules-table-body]");
  const sortButtons = Array.from(container.querySelectorAll("[data-rules-sort-field]"));
  const selectAllToggle = container.querySelector("[data-rules-select-all]");
  const includeDisabledToggle = container.querySelector("[data-rules-include-disabled]");
  const runSelectedButton = container.querySelector("[data-rules-run-selected]");
  const runAllButton = container.querySelector("[data-rules-run-all]");
  const viewModeButtons = Array.from(container.querySelectorAll("[data-rules-view-mode-button]"));
  const saveDefaultsButton = container.querySelector("[data-rules-save-defaults]");
  const runStatus = container.querySelector("[data-rules-run-status]");
  const schedulePanel = container.querySelector("[data-rules-schedule]");
  const scheduleEnabledInput = container.querySelector("[data-rules-schedule-enabled]");
  const scheduleIntervalInput = container.querySelector("[data-rules-schedule-interval]");
  const scheduleScopeInput = container.querySelector("[data-rules-schedule-scope]");
  const scheduleSaveButton = container.querySelector("[data-rules-schedule-save]");
  const scheduleRunNowButton = container.querySelector("[data-rules-schedule-run-now]");
  const scheduleStatus = container.querySelector("[data-rules-schedule-status]");
  const hoverPoster = container.querySelector("[data-rules-hover-poster]");
  const hoverPosterImage = hoverPoster?.querySelector("[data-rules-hover-image]");
  const hoverPosterTitle = hoverPoster?.querySelector("[data-rules-hover-title]");
  const sortInput = filterForm?.querySelector("[data-rules-sort-input]");
  const directionInput = filterForm?.querySelector("[data-rules-direction-input]");
  const viewInput = filterForm?.querySelector("[data-rules-view-input]");

  const VIEW_MODES = new Set(["table", "cards"]);
  const SORT_FIELDS = new Set([
    "updated_at",
    "rule_name",
    "media_type",
    "last_sync_status",
    "enabled",
    "release_state",
    "exact_filtered_count",
    "combined_filtered_count",
    "combined_fetched_count",
    "last_snapshot_at",
  ]);
  const SYNC_STATUS_RANK = {
    ok: 0,
    never: 1,
    drift: 2,
    error: 3,
  };
  const defaultDirectionByField = {
    updated_at: "desc",
    rule_name: "asc",
    media_type: "asc",
    last_sync_status: "asc",
    enabled: "desc",
    release_state: "asc",
    exact_filtered_count: "desc",
    combined_filtered_count: "desc",
    combined_fetched_count: "desc",
    last_snapshot_at: "desc",
  };
  const normalizeViewMode = (value) => (VIEW_MODES.has(String(value || "").trim()) ? String(value).trim() : "table");
  const normalizeSortField = (value) => (SORT_FIELDS.has(String(value || "").trim()) ? String(value).trim() : "updated_at");
  const normalizeSortDirection = (value) => (String(value || "").trim().toLowerCase() === "asc" ? "asc" : "desc");

  const entries = Array.from(container.querySelectorAll("[data-rule-id]")).reduce((map, element) => {
    const ruleId = String(element.dataset.ruleId || "").trim();
    if (!ruleId) {
      return map;
    }
    const existing = map.get(ruleId) || {
      id: ruleId,
      row: null,
      card: null,
      checkboxes: [],
      name: "",
      mediaType: "",
      releaseRank: 99,
      exactFilteredCount: 0,
      filteredCount: 0,
      fetchedCount: 0,
      lastSnapshotAtMs: 0,
      lastSyncStatus: "",
      enabled: 0,
      updatedAtMs: 0,
      posterUrl: "",
      posterTitle: "",
    };
    if (element.matches("[data-rules-row]")) {
      existing.row = element;
    }
    if (element.matches("[data-rules-card]")) {
      existing.card = element;
    }
    existing.name = String(element.dataset.ruleName || existing.name || "").trim();
    existing.mediaType = String(element.dataset.ruleMediaType || existing.mediaType || "").trim();
    existing.releaseRank = Number(element.dataset.ruleReleaseRank || existing.releaseRank || 99);
    existing.exactFilteredCount = Number(
      element.dataset.ruleExactFilteredCount || existing.exactFilteredCount || 0
    );
    existing.filteredCount = Number(element.dataset.ruleFilteredCount || existing.filteredCount || 0);
    existing.fetchedCount = Number(element.dataset.ruleFetchedCount || existing.fetchedCount || 0);
    existing.lastSnapshotAtMs = Date.parse(String(element.dataset.ruleLastSnapshotAt || "")) || 0;
    existing.lastSyncStatus = String(element.dataset.ruleLastSyncStatus || existing.lastSyncStatus || "").trim();
    existing.enabled = Number(element.dataset.ruleEnabled || existing.enabled || 0);
    existing.updatedAtMs = Date.parse(String(element.dataset.ruleUpdatedAt || "")) || 0;
    existing.posterUrl = String(element.dataset.rulePosterUrl || existing.posterUrl || "").trim();
    existing.posterTitle = String(element.dataset.rulePosterTitle || existing.posterTitle || "").trim();
    map.set(ruleId, existing);
    return map;
  }, new Map());

  for (const checkbox of container.querySelectorAll("[data-rules-select-rule]")) {
    const ruleId = String(checkbox.value || "").trim();
    const entry = entries.get(ruleId);
    if (!entry) {
      continue;
    }
    entry.checkboxes.push(checkbox);
  }

  const state = {
    viewMode: normalizeViewMode(container.dataset.defaultViewMode || container.dataset.defaultSettingsViewMode || "table"),
    sortField: normalizeSortField(container.dataset.defaultSortField || container.dataset.defaultSettingsSortField || "updated_at"),
    sortDirection: normalizeSortDirection(
      container.dataset.defaultSortDirection || container.dataset.defaultSettingsSortDirection || "desc"
    ),
  };

  const setRunStatus = (message, isError = false) => {
    if (!runStatus) {
      return;
    }
    runStatus.textContent = message;
    runStatus.style.color = isError ? "var(--danger)" : "";
  };

  const rulesPageUrl = new URL(window.location.href);
  const hasExplicitFilterParams = () => FILTER_FIELD_NAMES.some((name) => {
    const value = rulesPageUrl.searchParams.get(name);
    return Boolean(String(value || "").trim());
  });

  const readStoredFilterState = () => {
    try {
      return parseJsonData(window.localStorage.getItem(FILTER_STORAGE_KEY), null);
    } catch {
      return null;
    }
  };

  const readFilterStateFromForm = () => {
    const values = {};
    if (!filterForm) {
      return values;
    }
    for (const fieldName of FILTER_FIELD_NAMES) {
      const field = filterForm.querySelector(`[name="${fieldName}"]`);
      values[fieldName] = String(field?.value || "").trim();
    }
    return values;
  };

  const persistFilterState = () => {
    if (!filterForm) {
      return;
    }
    try {
      window.localStorage.setItem(
        FILTER_STORAGE_KEY,
        JSON.stringify(readFilterStateFromForm())
      );
    } catch {
      // Ignore storage failures and keep the page functional.
    }
  };

  const applyStoredFilterState = (storedValues) => {
    if (!filterForm || !storedValues || typeof storedValues !== "object") {
      return false;
    }
    let changed = false;
    for (const fieldName of FILTER_FIELD_NAMES) {
      const field = filterForm.querySelector(`[name="${fieldName}"]`);
      if (!field) {
        continue;
      }
      const nextValue = String(storedValues[fieldName] || "").trim();
      if (String(field.value || "").trim() === nextValue) {
        continue;
      }
      field.value = nextValue;
      changed = true;
    }
    return changed;
  };

  const restoreFilterState = () => {
    if (!filterForm) {
      return;
    }
    if (hasExplicitFilterParams()) {
      window.sessionStorage.removeItem(FILTER_RESTORE_FLAG_KEY);
      persistFilterState();
      return;
    }
    if (window.sessionStorage.getItem(FILTER_RESTORE_FLAG_KEY) === "1") {
      window.sessionStorage.removeItem(FILTER_RESTORE_FLAG_KEY);
      return;
    }
    const storedValues = readStoredFilterState();
    const hasStoredFilters = FILTER_FIELD_NAMES.some((fieldName) => {
      return Boolean(String(storedValues?.[fieldName] || "").trim());
    });
    if (!hasStoredFilters) {
      return;
    }
    if (!applyStoredFilterState(storedValues)) {
      return;
    }
    window.sessionStorage.setItem(FILTER_RESTORE_FLAG_KEY, "1");
    syncFilterHiddenInputs();
    filterForm.requestSubmit();
  };

  const syncFilterHiddenInputs = () => {
    if (sortInput) {
      sortInput.value = state.sortField;
    }
    if (directionInput) {
      directionInput.value = state.sortDirection;
    }
    if (viewInput) {
      viewInput.value = state.viewMode;
    }
  };

  const compareEntries = (left, right) => {
    const compareString = (a, b) => String(a || "").localeCompare(String(b || ""), undefined, { sensitivity: "base" });
    const compareNumeric = (a, b) => Number(a || 0) - Number(b || 0);
    let result = 0;
    switch (state.sortField) {
      case "rule_name":
        result = compareString(left.name, right.name);
        break;
      case "media_type":
        result = compareString(left.mediaType, right.mediaType);
        break;
      case "last_sync_status":
        result = compareNumeric(
          SYNC_STATUS_RANK[left.lastSyncStatus] ?? 9,
          SYNC_STATUS_RANK[right.lastSyncStatus] ?? 9
        );
        break;
      case "enabled":
        result = compareNumeric(left.enabled, right.enabled);
        break;
      case "release_state":
        result = compareNumeric(left.releaseRank, right.releaseRank);
        break;
      case "exact_filtered_count":
        result = compareNumeric(left.exactFilteredCount, right.exactFilteredCount);
        break;
      case "combined_filtered_count":
        result = compareNumeric(left.filteredCount, right.filteredCount);
        break;
      case "combined_fetched_count":
        result = compareNumeric(left.fetchedCount, right.fetchedCount);
        break;
      case "last_snapshot_at":
        result = compareNumeric(left.lastSnapshotAtMs, right.lastSnapshotAtMs);
        break;
      case "updated_at":
      default:
        result = compareNumeric(left.updatedAtMs, right.updatedAtMs);
        break;
    }
    if (result === 0) {
      result = compareString(left.name, right.name);
    }
    if (state.sortDirection === "desc") {
      result *= -1;
    }
    return result;
  };

  const sortEntries = () => {
    const sorted = Array.from(entries.values()).sort(compareEntries);
    if (tableBody) {
      for (const entry of sorted) {
        if (entry.row) {
          tableBody.appendChild(entry.row);
        }
      }
    }
    if (cardsWrap) {
      for (const entry of sorted) {
        if (entry.card) {
          cardsWrap.appendChild(entry.card);
        }
      }
    }
  };

  const applyViewMode = () => {
    const tableMode = state.viewMode === "table";
    if (tableWrap) {
      tableWrap.hidden = !tableMode;
    }
    if (cardsWrap) {
      cardsWrap.hidden = tableMode;
    }
    for (const button of viewModeButtons) {
      const mode = String(button.dataset.rulesViewModeButton || "").trim();
      const active = mode === state.viewMode;
      button.dataset.active = active ? "1" : "0";
      button.setAttribute("aria-pressed", active ? "true" : "false");
      button.classList.toggle("muted", !active);
    }
    if (hoverPoster) {
      hoverPoster.hidden = true;
    }
  };

  const sortGlyphFor = (field) => {
    const numericFields = new Set([
      "updated_at",
      "enabled",
      "release_state",
      "exact_filtered_count",
      "combined_filtered_count",
      "combined_fetched_count",
      "last_snapshot_at",
    ]);
    const numeric = numericFields.has(field);
    if (numeric) {
      return state.sortDirection === "asc" ? "0-9" : "9-0";
    }
    return state.sortDirection === "asc" ? "A-Z" : "Z-A";
  };

  const renderSortHeaders = () => {
    for (const button of sortButtons) {
      const field = normalizeSortField(button.dataset.rulesSortField || "");
      const glyph = button.querySelector("[data-rules-sort-glyph]");
      const active = field === state.sortField;
      button.dataset.sortActive = active ? "1" : "0";
      button.setAttribute("aria-pressed", active ? "true" : "false");
      if (glyph) {
        glyph.textContent = active ? sortGlyphFor(field) : "↕";
      }
    }
  };

  const setSelectionForRule = (ruleId, checked) => {
    const entry = entries.get(ruleId);
    if (!entry) {
      return;
    }
    for (const checkbox of entry.checkboxes) {
      checkbox.checked = checked;
    }
  };

  const visibleCheckboxes = () => {
    const tableMode = state.viewMode === "table";
    const checkboxes = [];
    for (const entry of entries.values()) {
      const host = tableMode ? entry.row : entry.card;
      if (!host || host.hidden) {
        continue;
      }
      const candidate = entry.checkboxes.find((input) => input.closest(tableMode ? "[data-rules-row]" : "[data-rules-card]"));
      if (candidate) {
        checkboxes.push(candidate);
      }
    }
    return checkboxes;
  };

  const selectedRuleIds = () => {
    const selected = [];
    const seen = new Set();
    for (const entry of entries.values()) {
      if (!entry.checkboxes.some((input) => input.checked)) {
        continue;
      }
      if (seen.has(entry.id)) {
        continue;
      }
      seen.add(entry.id);
      selected.push(entry.id);
    }
    return selected;
  };

  const runBatchFetch = async ({ runAll, ruleIds }) => {
    if (!runAll && ruleIds.length === 0) {
      setRunStatus("Select at least one rule first.", true);
      return;
    }
    const includeDisabled = Boolean(includeDisabledToggle?.checked);
    const buttons = [runSelectedButton, runAllButton].filter(Boolean);
    for (const button of buttons) {
      button.disabled = true;
    }
    setRunStatus("Running Jackett fetch...");
    try {
      const response = await fetch("/api/rules/fetch", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          run_all: runAll,
          rule_ids: ruleIds,
          include_disabled: includeDisabled,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(String(payload?.message || payload?.error || "Could not run rule fetch."));
      }
      setRunStatus(String(payload?.message || "Rule fetch completed."));
      window.setTimeout(() => {
        window.location.reload();
      }, 450);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not run rule fetch.";
      setRunStatus(message, true);
    } finally {
      for (const button of buttons) {
        button.disabled = false;
      }
    }
  };

  const readScheduleState = () => {
    const fallback = {
      enabled: false,
      interval_minutes: 360,
      scope: "enabled",
      last_status: "idle",
      last_message: "",
      last_run_at: null,
      next_run_at: null,
    };
    if (!schedulePanel) {
      return fallback;
    }
    return {
      ...fallback,
      ...parseJsonData(schedulePanel.dataset.rulesSchedule || "", fallback),
    };
  };

  let scheduleState = readScheduleState();

  const renderScheduleStatus = () => {
    if (!scheduleStatus) {
      return;
    }
    const parts = [`Last status: ${scheduleState.last_status || "idle"}.`];
    if (scheduleState.last_message) {
      parts.push(String(scheduleState.last_message));
    }
    if (scheduleState.last_run_at) {
      parts.push(`Last run ${scheduleState.last_run_at}.`);
    }
    if (scheduleState.next_run_at) {
      parts.push(`Next run ${scheduleState.next_run_at}.`);
    }
    scheduleStatus.textContent = parts.join(" ");
  };

  const saveSchedule = async () => {
    if (!scheduleSaveButton) {
      return;
    }
    scheduleSaveButton.disabled = true;
    if (scheduleRunNowButton) {
      scheduleRunNowButton.disabled = true;
    }
    try {
      const response = await fetch("/api/rules/fetch-schedule", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          enabled: Boolean(scheduleEnabledInput?.checked),
          interval_minutes: Number(scheduleIntervalInput?.value || 360),
          scope: String(scheduleScopeInput?.value || "enabled"),
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(String(payload?.error || "Could not save schedule."));
      }
      scheduleState = payload.schedule || scheduleState;
      renderScheduleStatus();
      setRunStatus("Schedule saved.");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not save schedule.";
      setRunStatus(message, true);
    } finally {
      scheduleSaveButton.disabled = false;
      if (scheduleRunNowButton) {
        scheduleRunNowButton.disabled = false;
      }
    }
  };

  const runScheduleNow = async () => {
    if (!scheduleRunNowButton) {
      return;
    }
    scheduleRunNowButton.disabled = true;
    if (scheduleSaveButton) {
      scheduleSaveButton.disabled = true;
    }
    setRunStatus("Running scheduled fetch now...");
    try {
      const response = await fetch("/api/rules/fetch-schedule/run-now", {
        method: "POST",
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(String(payload?.message || payload?.error || "Could not run schedule now."));
      }
      scheduleState = payload.schedule || scheduleState;
      renderScheduleStatus();
      setRunStatus(String(payload?.message || "Scheduled run completed."));
      window.setTimeout(() => {
        window.location.reload();
      }, 450);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not run schedule now.";
      setRunStatus(message, true);
    } finally {
      scheduleRunNowButton.disabled = false;
      if (scheduleSaveButton) {
        scheduleSaveButton.disabled = false;
      }
    }
  };

  const saveRulesPageDefaults = async () => {
    if (!saveDefaultsButton) {
      return;
    }
    saveDefaultsButton.disabled = true;
    setRunStatus("Saving rules-page defaults...");
    try {
      const response = await fetch("/api/rules/page-preferences", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          view_mode: state.viewMode,
          sort_field: state.sortField,
          sort_direction: state.sortDirection,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(String(payload?.error || "Could not save defaults."));
      }
      setRunStatus("Saved rules-page defaults.");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not save defaults.";
      setRunStatus(message, true);
    } finally {
      saveDefaultsButton.disabled = false;
    }
  };

  const currentUrl = new URL(window.location.href);
  const hoverDebugEnabled = currentUrl.searchParams.get("hover_debug") === "1";
  const hoverDebugSessionId = hoverDebugEnabled
    ? currentUrl.searchParams.get("hover_debug_session") || `hover-${Date.now().toString(36)}`
    : "";
  const hoverDebugScrollMode = hoverDebugEnabled ? currentUrl.searchParams.get("hover_debug_scroll") || "" : "";
  const hoverDebugAutoplay = hoverDebugEnabled && currentUrl.searchParams.get("hover_debug_autoplay") === "1";
  const hoverDebugSampleCount = hoverDebugEnabled
    ? Math.max(2, Math.min(8, Number.parseInt(currentUrl.searchParams.get("hover_debug_samples") || "4", 10) || 4))
    : 0;
  let hoverDebugSequence = 0;
  let lastHoverDebugLogAt = 0;
  let activeHoverEntry = null;
  let activeHoverPointer = null;
  let hoverRepositionFrameId = 0;
  let hoverDebugAutoplayStarted = false;

  const clearHoverRepositionFrame = () => {
    if (!hoverRepositionFrameId) {
      return;
    }
    window.cancelAnimationFrame(hoverRepositionFrameId);
    hoverRepositionFrameId = 0;
  };

  const updateHoverPointer = (event) => {
    if (!(event instanceof MouseEvent)) {
      return;
    }
    activeHoverPointer = {
      x: event.clientX,
      y: event.clientY,
    };
  };

  const rectSnapshot = (rect) => ({
    left: Math.round(rect.left),
    top: Math.round(rect.top),
    right: Math.round(rect.right),
    bottom: Math.round(rect.bottom),
    width: Math.round(rect.width),
    height: Math.round(rect.height),
  });

  const emitHoverDebug = (reason, entry, details = {}) => {
    if (!hoverDebugEnabled || !hoverPoster || !entry?.row) {
      return;
    }
    const now = Date.now();
    if (reason === "mousemove" && now - lastHoverDebugLogAt < 250) {
      return;
    }
    lastHoverDebugLogAt = now;
    const anchor = entry.row.querySelector(".rules-title-cell") || entry.row;
    const payload = {
      session_id: hoverDebugSessionId,
      sequence: ++hoverDebugSequence,
      reason,
      href: window.location.href,
      row_id: entry.id,
      row_name: entry.name,
      poster_url: entry.posterUrl,
      hover_side: hoverPoster.dataset.hoverSide || "",
      hover_vertical_side: hoverPoster.dataset.hoverVerticalSide || "",
      hidden: Boolean(hoverPoster.hidden),
      pointer: activeHoverPointer ? { ...activeHoverPointer } : null,
      viewport: {
        width: window.innerWidth,
        height: window.innerHeight,
        scroll_x: Math.round(window.scrollX),
        scroll_y: Math.round(window.scrollY),
      },
      row_rect: rectSnapshot(entry.row.getBoundingClientRect()),
      anchor_rect: rectSnapshot(anchor.getBoundingClientRect()),
      poster_rect: rectSnapshot(hoverPoster.getBoundingClientRect()),
      styles: {
        left: hoverPoster.style.left || "",
        top: hoverPoster.style.top || "",
        right: hoverPoster.style.right || "",
        width: hoverPoster.style.width || "",
        height: hoverPoster.style.height || "",
        max_height: hoverPoster.style.maxHeight || "",
      },
      extra: details,
    };
    window.fetch("/api/debug/hover-telemetry", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => {});
  };

  const positionHoverPoster = (entry, reason = "position") => {
    if (!hoverPoster || !entry?.row) {
      return;
    }
    const rowRect = entry.row.getBoundingClientRect();
    const anchor = entry.row.querySelector(".rules-title-cell") || entry.row;
    if (!anchor) {
      return;
    }
    if (rowRect.width <= 0 || rowRect.height <= 0) {
      return;
    }
    const anchorRect = anchor.getBoundingClientRect();

    if (hoverPoster.parentElement !== document.body) {
      document.body.appendChild(hoverPoster);
    }

    const viewportMargin = 12;
    const anchorGap = 10;
    const minPosterHeight = 140;
    const defaultPosterWidth = Math.max(120, Math.min(window.innerWidth * 0.16, 200));
    const defaultPosterHeight = Math.round(defaultPosterWidth * 1.55);
    const availableBelowFromAnchorTop = Math.max(
      0,
      Math.round(window.innerHeight - viewportMargin - anchorRect.top)
    );
    const availableAboveFromRowBottom = Math.max(0, Math.round(rowRect.bottom - viewportMargin));
    let verticalSide = availableBelowFromAnchorTop >= minPosterHeight ? "below" : "above";
    let posterHeight =
      verticalSide === "below"
        ? Math.min(defaultPosterHeight, Math.max(minPosterHeight, availableBelowFromAnchorTop))
        : Math.min(
            defaultPosterHeight,
            availableAboveFromRowBottom,
            Math.max(minPosterHeight, availableBelowFromAnchorTop + Math.round(rowRect.height * 0.35))
          );
    if (!Number.isFinite(posterHeight) || posterHeight <= 0) {
      posterHeight = minPosterHeight;
    }
    let posterWidth = Math.max(96, Math.round(posterHeight / 1.55));
    hoverPoster.style.width = `${posterWidth}px`;
    hoverPoster.style.height = `${posterHeight}px`;
    hoverPoster.style.maxHeight = `${posterHeight}px`;
    const roomOnRight = anchorRect.right + anchorGap + posterWidth <= window.innerWidth - viewportMargin;
    const nextLeft = roomOnRight
      ? Math.min(anchorRect.right + anchorGap, window.innerWidth - viewportMargin - posterWidth)
      : Math.max(viewportMargin, anchorRect.left - anchorGap - posterWidth);
    let nextTop = Math.max(
      viewportMargin,
      Math.min(anchorRect.top - 4, window.innerHeight - viewportMargin - posterHeight)
    );

    if (verticalSide === "below" && anchorRect.top + posterHeight > window.innerHeight - viewportMargin) {
      verticalSide = "above";
      posterHeight = Math.min(
        defaultPosterHeight,
        availableAboveFromRowBottom || posterHeight,
        Math.max(minPosterHeight, availableBelowFromAnchorTop + Math.round(rowRect.height * 0.35))
      );
      posterWidth = Math.max(96, Math.round(posterHeight / 1.55));
      hoverPoster.style.width = `${posterWidth}px`;
      hoverPoster.style.height = `${posterHeight}px`;
      hoverPoster.style.maxHeight = `${posterHeight}px`;
    }
    if (verticalSide === "above") {
      nextTop = Math.max(
        viewportMargin,
        Math.min(rowRect.bottom - anchorGap - posterHeight, window.innerHeight - viewportMargin - posterHeight)
      );
    }

    hoverPoster.dataset.hoverSide = roomOnRight ? "right" : "left";
    hoverPoster.dataset.hoverVerticalSide = verticalSide;
    hoverPoster.style.left = `${Math.round(nextLeft)}px`;
    hoverPoster.style.top = `${Math.round(nextTop)}px`;
    hoverPoster.style.right = "";
    emitHoverDebug(reason, entry, {
      available_below_from_anchor_top: availableBelowFromAnchorTop,
      available_above_from_row_bottom: availableAboveFromRowBottom,
      computed_width: posterWidth,
      computed_height: posterHeight,
    });
  };

  const scheduleHoverPosterReposition = (reason = "frame") => {
    if (!hoverPoster || !activeHoverEntry || hoverPoster.hidden || state.viewMode !== "table") {
      return;
    }
    clearHoverRepositionFrame();
    hoverRepositionFrameId = window.requestAnimationFrame(() => {
      hoverRepositionFrameId = 0;
      if (!activeHoverEntry?.row || !activeHoverEntry.row.matches(":hover")) {
        hoverPoster.hidden = true;
        activeHoverEntry = null;
        return;
      }
      positionHoverPoster(activeHoverEntry, reason);
    });
  };

  const showHoverPoster = (entry, event) => {
    if (!hoverPoster || !hoverPosterImage || !hoverPosterTitle) {
      return;
    }
    if (state.viewMode !== "table" || !entry.posterUrl) {
      hoverPoster.hidden = true;
      activeHoverEntry = null;
      activeHoverPointer = null;
      return;
    }
    updateHoverPointer(event);
    activeHoverEntry = entry;
    hoverPosterImage.src = entry.posterUrl;
    hoverPosterImage.alt = `${entry.posterTitle || entry.name} poster`;
    hoverPosterTitle.textContent = entry.posterTitle || entry.name;
    hoverPoster.hidden = false;
    positionHoverPoster(entry, "mouseenter");
    scheduleHoverPosterReposition("mouseenter");
  };

  const runHoverDebugAutoplay = () => {
    if (!hoverDebugAutoplay || hoverDebugAutoplayStarted || state.viewMode !== "table") {
      return;
    }
    const posterEntries = Array.from(entries.values()).filter((entry) => entry.row && entry.posterUrl);
    if (!posterEntries.length) {
      return;
    }
    hoverDebugAutoplayStarted = true;
    if (hoverDebugScrollMode === "bottom") {
      const lastEntry = posterEntries[posterEntries.length - 1];
      lastEntry?.row?.scrollIntoView({ block: "end", inline: "nearest" });
    }
    window.setTimeout(() => {
      const viewportHeight = window.innerHeight;
      const visibleEntries = posterEntries.filter((entry) => {
        const rowRect = entry.row?.getBoundingClientRect();
        return Boolean(rowRect && rowRect.top >= 0 && rowRect.bottom <= viewportHeight + 1);
      });
      const sampleEntries = visibleEntries.slice(-Math.max(2, Math.min(hoverDebugSampleCount, visibleEntries.length)));
      sampleEntries.forEach((entry, index) => {
        window.setTimeout(() => {
          if (!entry.row) {
            return;
          }
          const rowRect = entry.row.getBoundingClientRect();
          const anchor = entry.row.querySelector(".rules-title-cell") || entry.row;
          const anchorRect = anchor.getBoundingClientRect();
          const pointerX = Math.round(anchorRect.left + Math.max(16, Math.min(anchorRect.width * 0.12, 32)));
          const pointerY = Math.round(rowRect.top + rowRect.height / 2);
          showHoverPoster(
            entry,
            new MouseEvent("mouseenter", {
              bubbles: true,
              clientX: pointerX,
              clientY: pointerY,
            })
          );
        }, index * 700);
      });
    }, 320);
  };

  const hideHoverPoster = () => {
    if (!hoverPoster) {
      return;
    }
    const previousEntry = activeHoverEntry;
    clearHoverRepositionFrame();
    activeHoverEntry = null;
    activeHoverPointer = null;
    hoverPoster.hidden = true;
    emitHoverDebug("mouseleave", previousEntry, {});
  };

  for (const entry of entries.values()) {
    if (!entry.row) {
      continue;
    }
    entry.row.addEventListener("mouseenter", (event) => showHoverPoster(entry, event));
    entry.row.addEventListener("mousemove", (event) => {
      updateHoverPointer(event);
      scheduleHoverPosterReposition("mousemove");
    });
    entry.row.addEventListener("mouseleave", hideHoverPoster);
  }

  window.addEventListener("resize", () => scheduleHoverPosterReposition("resize"));
  window.addEventListener("scroll", () => scheduleHoverPosterReposition("scroll"), { passive: true });
  hoverPosterImage?.addEventListener("load", () => scheduleHoverPosterReposition("image-load"));
  hoverPosterImage?.addEventListener("error", () => scheduleHoverPosterReposition("image-error"));
  window.setTimeout(runHoverDebugAutoplay, 450);

  for (const entry of entries.values()) {
    for (const checkbox of entry.checkboxes) {
      checkbox.addEventListener("change", () => {
        setSelectionForRule(entry.id, checkbox.checked);
      });
    }
  }

  selectAllToggle?.addEventListener("change", () => {
    const visible = visibleCheckboxes();
    for (const checkbox of visible) {
      checkbox.checked = Boolean(selectAllToggle.checked);
      checkbox.dispatchEvent(new Event("change"));
    }
  });

  runSelectedButton?.addEventListener("click", () => {
    runBatchFetch({
      runAll: false,
      ruleIds: selectedRuleIds(),
    });
  });

  runAllButton?.addEventListener("click", () => {
    runBatchFetch({
      runAll: true,
      ruleIds: [],
    });
  });

  for (const button of viewModeButtons) {
    button.addEventListener("click", () => {
      const mode = normalizeViewMode(button.dataset.rulesViewModeButton || "table");
      state.viewMode = mode;
      applyViewMode();
      syncFilterHiddenInputs();
    });
  }

  for (const button of sortButtons) {
    button.addEventListener("click", () => {
      const field = normalizeSortField(button.dataset.rulesSortField || "updated_at");
      if (state.sortField === field) {
        state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
      } else {
        state.sortField = field;
        state.sortDirection = normalizeSortDirection(defaultDirectionByField[field] || "asc");
      }
      sortEntries();
      renderSortHeaders();
      syncFilterHiddenInputs();
    });
  }

  saveDefaultsButton?.addEventListener("click", saveRulesPageDefaults);
  scheduleSaveButton?.addEventListener("click", saveSchedule);
  scheduleRunNowButton?.addEventListener("click", runScheduleNow);

  filterForm?.addEventListener("submit", () => {
    persistFilterState();
    syncFilterHiddenInputs();
  });

  restoreFilterState();
  sortEntries();
  renderSortHeaders();
  applyViewMode();
  syncFilterHiddenInputs();
  renderScheduleStatus();
}

document.addEventListener("DOMContentLoaded", () => {
  initResultQueueActions(document);

  const searchPage = document.querySelector("[data-search-page]");
  if (searchPage) {
    initSearchPage(searchPage);
  }

  const ruleForm = document.querySelector("[data-rule-form]");
  if (ruleForm) {
    initRuleForm(ruleForm);
  }

  const settingsForm = document.querySelector("[data-settings-form]");
  if (settingsForm) {
    initSettingsForm(settingsForm);
  }

  const rulesPage = document.querySelector("[data-rules-page]");
  if (rulesPage) {
    initRulesPage(rulesPage);
  }
});
