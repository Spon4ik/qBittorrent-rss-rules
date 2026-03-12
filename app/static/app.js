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
    syncFromStateInputs() {
      for (const tokenItem of tokenItems) {
        syncQualityTokenItemFromStateInputs(tokenItem);
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

function buildEpisodeProgressRegexFragment(startSeasonValue, startEpisodeValue) {
  const startSeason = normalizeBoundedPositiveInt(startSeasonValue, { min: 1, max: 99 });
  const startEpisode = normalizeBoundedPositiveInt(startEpisodeValue, { min: 1, max: 99 });
  if (startSeason === null || startEpisode === null) {
    return "";
  }
  const separators = "[\\s._-]*";
  const seasonExact = `0*${startSeason}`;
  const episodeAny = "0*[1-9]\\d?";
  const episodeGe = buildMinNumericPattern1To99(startEpisode);
  const fragments = [
    `s${seasonExact}${separators}e${episodeGe}`,
    `s${seasonExact}${separators}e${episodeAny}${separators}-${separators}(?:e)?${episodeGe}`,
  ];
  if (startSeason < 99) {
    const seasonAfter = buildMinNumericPattern1To99(startSeason + 1);
    fragments.unshift(`s${seasonAfter}${separators}e${episodeAny}`);
  }
  return `(?:${fragments.join("|")})`;
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
  const filterIndexersInput = form.querySelector('input[name="filter_indexers"]');
  const filterCategoryIdsInput = form.querySelector('input[name="filter_category_ids"]');
  const indexerMultiSelectOptions = form.querySelector('[data-search-multiselect-options="indexers"]');
  const indexerMultiSelectSummary = form.querySelector('[data-search-multiselect-summary="indexers"]');
  const indexerMultiSelectSelectAll = form.querySelector('[data-search-multiselect-select-all="indexers"]');
  const indexerMultiSelectClear = form.querySelector('[data-search-multiselect-clear="indexers"]');
  const categoryMultiSelectOptions = form.querySelector('[data-search-multiselect-options="categories"]');
  const categoryMultiSelectSummary = form.querySelector('[data-search-multiselect-summary="categories"]');
  const categoryMultiSelectSelectAll = form.querySelector('[data-search-multiselect-select-all="categories"]');
  const categoryMultiSelectClear = form.querySelector('[data-search-multiselect-clear="categories"]');
  const categoryScopeStatusElement = form.querySelector("[data-search-category-scope-status]");
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
  const controlSets = Array.from(container.querySelectorAll("[data-search-controls]")).map((controlContainer) => ({
    controlContainer,
    viewModeSelect: controlContainer.querySelector("[data-search-view-mode]"),
    sortFieldInputs: [1, 2, 3]
      .map((level) => controlContainer.querySelector(`[data-search-sort-field="${level}"]`))
      .filter(Boolean),
    sortDirectionInputs: [1, 2, 3]
      .map((level) => controlContainer.querySelector(`[data-search-sort-dir="${level}"]`))
      .filter(Boolean),
    saveDefaultsButton: controlContainer.querySelector("[data-search-save-defaults]"),
    saveDefaultsStatus: controlContainer.querySelector("[data-search-default-status]"),
  }));
  const allSortFieldInputs = controlSets.flatMap((set) => set.sortFieldInputs);
  const allSortDirectionInputs = controlSets.flatMap((set) => set.sortDirectionInputs);
  const saveDefaultsButtons = controlSets.map((set) => set.saveDefaultsButton).filter(Boolean);
  const saveDefaultsStatuses = controlSets.map((set) => set.saveDefaultsStatus).filter(Boolean);
  const getSearchQueryLabel = () => String(queryInput?.value || container.dataset.searchQuery || "").trim();
  const getSearchQuery = () => normalizeSearchText(getSearchQueryLabel());
  const getSearchImdbId = () => normalizeSearchImdbId(imdbIdInput?.value || "");
  const DEFAULT_SORT_FIELD = "published_at";
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
  const normalizeViewMode = (value) => {
    const cleaned = String(value || "").trim().toLocaleLowerCase();
    return cleaned === "cards" ? "cards" : "table";
  };
  let controlState = {
    viewMode: normalizeViewMode(container.dataset.defaultViewMode || "table"),
    sortCriteria: normalizeSortCriteria(parseJsonData(container.dataset.defaultSort || "", [])),
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

  const emptyFilters = () => ({
    query: "",
    imdbId: getSearchImdbId(),
    releaseYear: "",
    keywordsAll: [],
    keywordsAnyGroups: [],
    keywordsNot: [],
    qualityIncludeTokens: [],
    qualityExcludeTokens: [],
    qualityIncludeRegex: null,
    qualityExcludeRegex: null,
    generatedPatternRegex: null,
    sizeMinMb: null,
    sizeMaxMb: null,
    feedScopeBlocksAll: false,
    indexers: [],
    categories: [],
  });

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
    sizeMinMb: filters.sizeMinMb,
    sizeMaxMb: filters.sizeMaxMb,
    feedScopeBlocksAll: Boolean(filters.feedScopeBlocksAll),
    indexers: [...filters.indexers],
    categories: [...filters.categories],
  });

  const writeControlStateToSet = (controlSet, state) => {
    if (controlSet.viewModeSelect) {
      controlSet.viewModeSelect.value = state.viewMode;
    }
    for (const level of [1, 2, 3]) {
      const fieldInput = controlSet.sortFieldInputs[level - 1];
      const directionInput = controlSet.sortDirectionInputs[level - 1];
      const criterion = state.sortCriteria[level - 1];
      if (fieldInput) {
        fieldInput.value = criterion?.field || "";
      }
      if (directionInput) {
        directionInput.value = criterion?.direction || "asc";
      }
    }
  };

  const readControlStateFromSet = (controlSet) => {
    const viewMode = normalizeViewMode(controlSet.viewModeSelect?.value || controlState.viewMode);
    const rawSortCriteria = [1, 2, 3].map((level) => ({
      field: controlSet.sortFieldInputs[level - 1]?.value || "",
      direction: controlSet.sortDirectionInputs[level - 1]?.value || "asc",
    }));
    return {
      viewMode,
      sortCriteria: normalizeSortCriteria(rawSortCriteria),
    };
  };

  const syncControlSets = (sourceControlSet = null) => {
    for (const controlSet of controlSets) {
      if (sourceControlSet && controlSet === sourceControlSet) {
        continue;
      }
      writeControlStateToSet(controlSet, controlState);
    }
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

  const getGeneratedPatternForFilters = () => {
    if (searchPatternPreview) {
      return String(searchPatternPreview.value || "").trim();
    }
    if (generatedPatternInput?.id === "pattern-preview") {
      return String(derivePattern(form, qualityPatternMap, qualityTokenGroupMap) || "").trim();
    }
    return String(generatedPatternInput?.value || "").trim();
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

    let feedScopeBlocksAll = false;
    let selectedIndexers = parseSearchFilterList(filterIndexersInput?.value || "")
      .map((item) => item.toLocaleLowerCase());
    if (hasFeedSelectionConstraint()) {
      const selectedFeedIndexers = getSelectedFeedIndexerSlugs();
      if (selectedFeedIndexers.length === 0) {
        feedScopeBlocksAll = true;
        selectedIndexers = [];
      } else if (selectedIndexers.length === 0) {
        selectedIndexers = selectedFeedIndexers;
      } else {
        selectedIndexers = selectedIndexers.filter((item) => selectedFeedIndexers.includes(item));
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
      generatedPatternRegex: compileGeneratedPatternRegex(getGeneratedPatternForFilters()),
      sizeMinMb: parseSearchMb(sizeMinInput?.value || ""),
      sizeMaxMb: parseSearchMb(sizeMaxInput?.value || ""),
      feedScopeBlocksAll,
      indexers: selectedIndexers,
      categories: parseSearchFilterList(filterCategoryIdsInput?.value || "")
        .map((item) => normalizeCategoryFilterValue(item))
        .filter(Boolean),
    };
  };

  const buildFilterValues = (filters) => {
    const values = [];
    if (filters.query) {
      const activeQueryLabel = getSearchQueryLabel();
      values.push({
        kind: "query",
        label: `Title query: ${activeQueryLabel || filters.query}`,
        value: filters.query,
      });
    }
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
    for (const indexer of filters.indexers) {
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

  const filtersWithOnlyValue = (filterValue) => {
    const filters = emptyFilters();
    if (filterValue.kind === "query") {
      filters.query = filterValue.value;
    } else if (filterValue.kind === "release_year") {
      filters.releaseYear = filterValue.value;
    } else if (filterValue.kind === "keywords_all") {
      filters.keywordsAll = [filterValue.value];
    } else if (filterValue.kind === "keywords_any_group") {
      filters.keywordsAnyGroups = [[...filterValue.value]];
    } else if (filterValue.kind === "keywords_not") {
      filters.keywordsNot = [filterValue.value];
    } else if (filterValue.kind === "quality_include_token") {
      filters.qualityIncludeTokens = [filterValue.value];
      filters.qualityIncludeRegex = compileQualityRegex(
        buildQualityIncludeRegex(filters.qualityIncludeTokens, qualityPatternMap, qualityTokenGroupMap)
      );
    } else if (filterValue.kind === "quality_exclude_token") {
      filters.qualityExcludeTokens = [filterValue.value];
      filters.qualityExcludeRegex = compileQualityRegex(buildQualityRegex(filters.qualityExcludeTokens, qualityPatternMap));
    } else if (filterValue.kind === "size_min_mb") {
      filters.sizeMinMb = filterValue.value;
    } else if (filterValue.kind === "size_max_mb") {
      filters.sizeMaxMb = filterValue.value;
    } else if (filterValue.kind === "feed_scope_none") {
      filters.feedScopeBlocksAll = true;
    } else if (filterValue.kind === "filter_indexer") {
      filters.indexers = [filterValue.value];
    } else if (filterValue.kind === "filter_category") {
      filters.categories = [filterValue.value];
    }
    return filters;
  };

  const filtersWithoutValue = (filters, filterValue) => {
    const next = cloneFilters(filters);
    if (filterValue.kind === "query") {
      next.query = "";
    } else if (filterValue.kind === "release_year") {
      next.releaseYear = "";
    } else if (filterValue.kind === "keywords_all") {
      next.keywordsAll = next.keywordsAll.filter((item) => normalizeSearchText(item) !== filterValue.matchKey);
    } else if (filterValue.kind === "keywords_any_group") {
      next.keywordsAnyGroups = next.keywordsAnyGroups.filter(
        (group) => group.map((item) => normalizeSearchText(item)).filter(Boolean).join("||") !== filterValue.matchKey
      );
    } else if (filterValue.kind === "keywords_not") {
      next.keywordsNot = next.keywordsNot.filter((item) => normalizeSearchText(item) !== filterValue.matchKey);
    } else if (filterValue.kind === "quality_include_token") {
      next.qualityIncludeTokens = next.qualityIncludeTokens.filter(
        (item) => normalizeSearchText(item) !== filterValue.matchKey
      );
      next.qualityIncludeRegex = compileQualityRegex(
        buildQualityIncludeRegex(next.qualityIncludeTokens, qualityPatternMap, qualityTokenGroupMap)
      );
    } else if (filterValue.kind === "quality_exclude_token") {
      next.qualityExcludeTokens = next.qualityExcludeTokens.filter(
        (item) => normalizeSearchText(item) !== filterValue.matchKey
      );
      next.qualityExcludeRegex = compileQualityRegex(buildQualityRegex(next.qualityExcludeTokens, qualityPatternMap));
    } else if (filterValue.kind === "size_min_mb") {
      next.sizeMinMb = null;
    } else if (filterValue.kind === "size_max_mb") {
      next.sizeMaxMb = null;
    } else if (filterValue.kind === "feed_scope_none") {
      next.feedScopeBlocksAll = false;
    } else if (filterValue.kind === "filter_indexer") {
      next.indexers = next.indexers.filter((item) => item !== filterValue.value);
    } else if (filterValue.kind === "filter_category") {
      next.categories = next.categories.filter((item) => item !== filterValue.value);
    }
    return next;
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
      return tokens.some((token) => variants.includes(token));
    }
    const seasonMatch = normalizedTerm.match(/^s0*(\d{1,2})$/u);
    if (seasonMatch) {
      const season = Number(seasonMatch[1]);
      const variants = [`s${season}`, `s${String(season).padStart(2, "0")}`];
      return tokens.some((token) => {
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
      });
    }
    const episodeMatch = normalizedTerm.match(/^e0*(\d{1,3})$/u);
    if (episodeMatch) {
      const episode = Number(episodeMatch[1]);
      const variants = [`e${episode}`, `e${String(episode).padStart(2, "0")}`];
      return tokens.some((token) => {
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
      });
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

  const matchesQuery = (titleSurface, normalizedQuery, entryImdbId, normalizedImdbId) => {
    if (normalizedImdbId && entryImdbId && entryImdbId === normalizedImdbId) {
      return true;
    }
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
    return queryTerms.every((term) => titleTerms.has(term));
  };

  const entryMatchesFilters = (entry, filters) => {
    if (!matchesQuery(entry.titleSurface, filters.query, entry.imdbId, filters.imdbId)) {
      return false;
    }
    if (filters.feedScopeBlocksAll) {
      return false;
    }

    for (const keyword of filters.keywordsAll) {
      if (!containsTerm(entry.textSurface, keyword)) {
        return false;
      }
    }

    for (const group of filters.keywordsAnyGroups) {
      if (!group.some((keyword) => containsTerm(entry.textSurface, keyword))) {
        return false;
      }
    }

    for (const keyword of filters.keywordsNot) {
      if (containsExcludedTerm(entry.textSurface, keyword)) {
        return false;
      }
    }

    if (filters.qualityIncludeRegex && !filters.qualityIncludeRegex.test(entry.regexSurface)) {
      return false;
    }
    if (filters.qualityExcludeRegex && filters.qualityExcludeRegex.test(entry.regexSurface)) {
      return false;
    }
    if (filters.generatedPatternRegex && !filters.generatedPatternRegex.test(entry.regexSurface)) {
      return false;
    }

    if (filters.releaseYear) {
      if (!entry.year || entry.year !== filters.releaseYear) {
        return false;
      }
    }

    if (filters.sizeMinMb !== null || filters.sizeMaxMb !== null) {
      if (entry.sizeBytes === null) {
        return false;
      }
      const sizeMb = entry.sizeBytes / (1024 * 1024);
      if (filters.sizeMinMb !== null && sizeMb < filters.sizeMinMb) {
        return false;
      }
      if (filters.sizeMaxMb !== null && sizeMb > filters.sizeMaxMb) {
        return false;
      }
    }

    if (filters.indexers.length > 0) {
      if (!entry.indexer || !filters.indexers.includes(entry.indexer)) {
        return false;
      }
    }

    if (filters.categories.length > 0) {
      if (
        entry.categoryValues.length === 0
        || !entry.categoryValues.some((item) => filters.categories.includes(item))
      ) {
        return false;
      }
    }

    return true;
  };

  const getSortCriteria = () => {
    return controlState.sortCriteria;
  };

  const compareEntries = (left, right, criteria) => {
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

  const sections = ["primary", "fallback"];
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
        title: String(card.dataset.title || "").trim(),
        titleSurface: normalizeSearchText(card.dataset.title || ""),
        textSurface: normalizeSearchText(card.dataset.textSurface || ""),
        regexSurface: String(card.dataset.textSurface || card.dataset.title || "").trim(),
        imdbId: normalizeSearchImdbId(card.dataset.imdbId || ""),
        indexerRaw: String(card.dataset.indexer || "").trim(),
        indexer: String(card.dataset.indexer || "").trim().toLocaleLowerCase(),
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
          emptyState: container.querySelector(`[data-search-empty="${section}"]`),
          filterImpactList: container.querySelector(`[data-filter-impact-list="${section}"]`),
          filterImpactEmpty: container.querySelector(`[data-filter-impact-empty="${section}"]`),
        },
      ];
    })
  );

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

  const renderFilterImpact = (section, filters, visibleCount) => {
    const state = sectionState[section];
    if (!state || !state.filterImpactList || !state.filterImpactEmpty) {
      return;
    }
    const values = buildFilterValues(filters);
    state.filterImpactList.innerHTML = "";
    if (values.length === 0) {
      state.filterImpactEmpty.hidden = false;
      return;
    }
    state.filterImpactEmpty.hidden = true;

    const total = state.entries.length;
    const emptyResultSet = total > 0 && visibleCount === 0;
    const formatResultCount = (count) => `${count} result${count === 1 ? "" : "s"}`;
    for (const filterValue of values) {
      const onlyFilters = filtersWithOnlyValue(filterValue);
      let onlyRemainCount = 0;
      for (const entry of state.entries) {
        if (entryMatchesFilters(entry, onlyFilters)) {
          onlyRemainCount += 1;
        }
      }
      const onlyFilteredOutCount = total - onlyRemainCount;
      let withoutThisCount = 0;
      let isBlocker = false;

      if (emptyResultSet) {
        const withoutThisFilters = filtersWithoutValue(filters, filterValue);
        for (const entry of state.entries) {
          if (entryMatchesFilters(entry, withoutThisFilters)) {
            withoutThisCount += 1;
          }
        }
        isBlocker = withoutThisCount > 0;
      }

      const item = document.createElement("li");
      item.className = "filter-impact-item";
      if (isBlocker) {
        item.classList.add("blocker");
      }

      const label = document.createElement("span");
      label.className = "filter-impact-label";
      label.textContent = `${filterValue.label}.`;

      const metrics = document.createElement("span");
      metrics.className = "filter-impact-metrics";
      metrics.textContent = `If applied alone: ${onlyRemainCount} remain; ${onlyFilteredOutCount} filtered out.`;

      item.append(label, metrics);

      if (emptyResultSet) {
        const blockerNote = document.createElement("span");
        blockerNote.className = "filter-impact-blocker-note";
        blockerNote.textContent = isBlocker
          ? `Blocks current list: removing this value would leave ${formatResultCount(withoutThisCount)}.`
          : "Not the only blocker: removing this value still leaves 0 results because other active filters also block matches.";
        item.appendChild(blockerNote);
      }

      state.filterImpactList.appendChild(item);
    }
  };

  const applyFiltersForSection = (section, filters, sortCriteria) => {
    const state = sectionState[section];
    if (!state) {
      return;
    }

    const sortedEntries = [...state.entries].sort((left, right) => compareEntries(left, right, sortCriteria));
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

    let visibleCount = 0;
    for (const entry of sortedEntries) {
      const visible = entryMatchesFilters(entry, filters);
      entry.card.hidden = !visible;
      if (entry.row) {
        entry.row.hidden = !visible;
      }
      if (visible) {
        visibleCount += 1;
      }
    }

    if (state.filteredCountElement) {
      state.filteredCountElement.textContent = String(visibleCount);
    }
    if (state.fetchedCountElement) {
      state.fetchedCountElement.textContent = String(state.entries.length);
    }
    if (state.emptyState) {
      state.emptyState.hidden = visibleCount > 0;
    }

    renderFilterImpact(section, filters, visibleCount);
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
    applyFiltersForSection("primary", filters, sortCriteria);
    applyFiltersForSection("fallback", filters, sortCriteria);
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

  for (const controlSet of controlSets) {
    const syncFromControlSet = () => {
      controlState = readControlStateFromSet(controlSet);
      syncControlSets(controlSet);
      applyLocalFilters();
    };
    if (controlSet.viewModeSelect) {
      controlSet.viewModeSelect.addEventListener("change", syncFromControlSet);
      controlSet.viewModeSelect.addEventListener("input", syncFromControlSet);
    }
    for (const input of [...controlSet.sortFieldInputs, ...controlSet.sortDirectionInputs]) {
      input.addEventListener("change", syncFromControlSet);
      input.addEventListener("input", syncFromControlSet);
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
      const ruleId = String(button.dataset.resultRuleId || "").trim();
      const queueOptions = readQueueOptions(button);
      const originalLabel = button.textContent;
      button.disabled = true;
      button.textContent = "Queueing...";
      setQueueStatus(button, "Queueing result in qBittorrent...");

      try {
        const response = await fetch("/api/search/queue", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            link: resultLink,
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
    qualityTokenControls.syncFromStateInputs();
    if (filterProfileSelect) {
      filterProfileSelect.value = profileKey;
    }
    syncQualityProfileValue();
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
      patternPreview.value = derivePattern(form, qualityPatternMap, qualityTokenGroupMap);
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
  filterProfileSelect?.addEventListener("change", () => {
    const selectedKey = filterProfileSelect.value;
    if (!selectedKey) {
      syncQualityProfileValue();
      refreshDerivedFields();
      return;
    }
    applyFilterProfile(selectedKey);
    refreshDerivedFields();
  });
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
    if (releaseYearInput && (!releaseYearTouched || !releaseYearInput.value.trim())) {
      releaseYearInput.value = normalizeReleaseYear(payload.year || "");
      releaseYearTouched = Boolean(releaseYearInput.value.trim());
    }

    categoryTouched = false;
    savePathTouched = false;
    refreshDerivedFields();
  });


  feedSelectAllButton?.addEventListener("click", () => {
    getFeedCheckboxes().forEach((checkbox) => {
      checkbox.checked = true;
    });
  });

  feedClearAllButton?.addEventListener("click", () => {
    getFeedCheckboxes().forEach((checkbox) => {
      checkbox.checked = false;
    });
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
  });

  runSearchHereLink?.addEventListener("click", (event) => {
    event.preventDefault();
    const href = runSearchHereLink.getAttribute("href") || "";
    if (!href) {
      return;
    }
    const url = new URL(href, window.location.origin);
    url.searchParams.set("feed_scope_override", "1");
    for (const input of getFeedCheckboxes()) {
      if (!input.checked) {
        continue;
      }
      url.searchParams.append("feed_urls", input.value);
    }
    window.location.href = `${url.pathname}${url.search}${url.hash}`;
  });

  applyMediaTypeVisibility(currentMediaType);
  syncQualityProfileValue();
  refreshDerivedFields();
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
});
