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

function derivePattern(form, qualityPatternMap) {
  const manualMustContain = form.querySelector('textarea[name="must_contain_override"]')?.value.trim();
  if (looksLikeFullMustContainOverride(manualMustContain)) {
    return manualMustContain;
  }
  const title = deriveTitle(form);
  const useRegex = Boolean(form.querySelector('input[name="use_regex"]')?.checked);
  const includeReleaseYear = Boolean(
    form.querySelector('input[type="checkbox"][name="include_release_year"]')?.checked
  );
  const releaseYear = normalizeReleaseYear(form.querySelector('input[name="release_year"]')?.value);
  const additionalIncludes = parseAdditionalIncludes(
    form.querySelector('textarea[name="additional_includes"]')?.value
  );
  const manualMustContainFragments = buildManualMustContainFragments(manualMustContain);
  const qualityIncludeTokens = getCheckedValues(form, "quality_include_tokens");
  const qualityExcludeTokens = getCheckedValues(form, "quality_exclude_tokens").filter(
    (token) => !qualityIncludeTokens.includes(token)
  );
  const qualityInclude = buildQualityRegex(qualityIncludeTokens, qualityPatternMap);
  const qualityExclude = buildQualityRegex(qualityExcludeTokens, qualityPatternMap);

  const hasGeneratedConditions = Boolean(
    (includeReleaseYear && releaseYear)
      || additionalIncludes.length
      || manualMustContainFragments.length
      || qualityInclude
      || qualityExclude
  );
  if (!useRegex && !hasGeneratedConditions) {
    return title;
  }

  const positiveFragments = [buildTitleRegexFragment(title)];
  if (includeReleaseYear && releaseYear) {
    positiveFragments.push(escapeRegex(releaseYear));
  }
  for (const item of additionalIncludes) {
    positiveFragments.push(buildTitleRegexFragment(item));
  }
  if (qualityInclude) {
    positiveFragments.push(qualityInclude);
  }
  for (const fragment of manualMustContainFragments) {
    positiveFragments.push(fragment);
  }

  let pattern = "(?i)";
  for (const fragment of positiveFragments) {
    if (!fragment) {
      continue;
    }
    pattern += `(?=.*${fragment})`;
  }
  if (qualityExclude) {
    pattern += `(?!.*${qualityExclude})`;
  }
  return pattern;
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

  const queryInput = form.querySelector('input[name="query"]');
  const mediaTypeInput = form.querySelector('select[name="media_type"]');
  const imdbIdInput = form.querySelector('input[name="imdb_id"]');
  const includeReleaseYearInput = form.querySelector('input[type="checkbox"][name="include_release_year"]');
  const releaseYearInput = form.querySelector('input[name="release_year"]');
  const keywordsAllInput = form.querySelector('input[name="keywords_all"]');
  const keywordsAnyInput = form.querySelector('input[name="keywords_any"]');
  const keywordsNotInput = form.querySelector('input[name="keywords_not"]');
  const sizeMinInput = form.querySelector('input[name="size_min_mb"]');
  const sizeMaxInput = form.querySelector('input[name="size_max_mb"]');
  const filterIndexersInput = form.querySelector('input[name="filter_indexers"]');
  const filterCategoryIdsInput = form.querySelector('input[name="filter_category_ids"]');
  const includeKeywordInputs = Array.from(form.querySelectorAll('input[name="quality_include_tokens"]'));
  const excludeKeywordInputs = Array.from(form.querySelectorAll('input[name="quality_exclude_tokens"]'));
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
  const searchQueryLabel = String(container.dataset.searchQuery || queryInput?.value || "").trim();
  const searchQuery = normalizeSearchText(searchQueryLabel);
  const searchImdbId = normalizeSearchImdbId(imdbIdInput?.value || "");
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
    imdbId: searchImdbId,
    releaseYear: "",
    keywordsAll: [],
    keywordsAnyGroups: [],
    keywordsNot: [],
    sizeMinMb: null,
    sizeMaxMb: null,
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

  const cloneFilters = (filters) => ({
    query: filters.query,
    imdbId: filters.imdbId,
    releaseYear: filters.releaseYear,
    keywordsAll: [...filters.keywordsAll],
    keywordsAnyGroups: filters.keywordsAnyGroups.map((group) => [...group]),
    keywordsNot: [...filters.keywordsNot],
    sizeMinMb: filters.sizeMinMb,
    sizeMaxMb: filters.sizeMaxMb,
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
      groupElement.querySelectorAll('input[type="checkbox"]').forEach((input) => {
        if (!groupVisible && input.checked) {
          input.checked = false;
        }
        input.disabled = !groupVisible;
      });
    });
    form.querySelectorAll("[data-search-quality-option]").forEach((optionElement) => {
      const optionScope = (optionElement.dataset.mediaTypes || "").split(",");
      const optionVisible = mediaTypeMatchesScope(mediaType, optionScope);
      optionElement.hidden = !optionVisible;
      optionElement.querySelectorAll('input[type="checkbox"]').forEach((input) => {
        if (!optionVisible && input.checked) {
          input.checked = false;
        }
        input.disabled = !optionVisible;
      });
    });
  };

  const getActiveFilters = () => ({
    ...(() => {
      const includeKeywordTerms = getCheckedValues(form, "quality_include_tokens");
      const excludeKeywordTerms = getCheckedValues(form, "quality_exclude_tokens");
      const keywordsAnyGroups = parseSearchAnyKeywordGroups(keywordsAnyInput?.value || "");
      if (includeKeywordTerms.length > 0) {
        keywordsAnyGroups.push(includeKeywordTerms);
      }
      return {
        query: searchQuery,
        imdbId: searchImdbId,
        releaseYear: includeReleaseYearInput?.checked
          ? normalizeReleaseYear(releaseYearInput?.value || "")
          : "",
        keywordsAll: parseSearchFilterList(keywordsAllInput?.value || ""),
        keywordsAnyGroups,
        keywordsNot: mergeUniqueTerms(
          parseSearchFilterList(keywordsNotInput?.value || ""),
          excludeKeywordTerms
        ),
      };
    })(),
    sizeMinMb: parseSearchMb(sizeMinInput?.value || ""),
    sizeMaxMb: parseSearchMb(sizeMaxInput?.value || ""),
    indexers: parseSearchFilterList(filterIndexersInput?.value || "").map((item) => item.toLocaleLowerCase()),
    categories: parseSearchFilterList(filterCategoryIdsInput?.value || "").map((item) => item.toLocaleLowerCase()),
  });

  const buildFilterValues = (filters) => {
    const values = [];
    if (filters.query) {
      values.push({
        kind: "query",
        label: `Title query: ${searchQueryLabel || filters.query}`,
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
        label: `Required keyword: ${keyword}`,
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
        label: `Excluded keyword: ${keyword}`,
        value: keyword,
        matchKey: normalizeSearchText(keyword),
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
    } else if (filterValue.kind === "size_min_mb") {
      filters.sizeMinMb = filterValue.value;
    } else if (filterValue.kind === "size_max_mb") {
      filters.sizeMaxMb = filterValue.value;
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
    } else if (filterValue.kind === "size_min_mb") {
      next.sizeMinMb = null;
    } else if (filterValue.kind === "size_max_mb") {
      next.sizeMaxMb = null;
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
      if (entry.categories.length === 0 || !entry.categories.some((item) => filters.categories.includes(item))) {
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
        imdbId: normalizeSearchImdbId(card.dataset.imdbId || ""),
        indexer: String(card.dataset.indexer || "").trim().toLocaleLowerCase(),
        sizeBytes: parseOptionalNumber(card.dataset.sizeBytes),
        publishedAtMs: parseIsoDateMs(card.dataset.publishedAt),
        year: normalizeReleaseYear(card.dataset.year || card.dataset.title || ""),
        seeders: parseOptionalNumber(card.dataset.seeders),
        peers: parseOptionalNumber(card.dataset.peers),
        leechers: parseOptionalNumber(card.dataset.leechers),
        grabs: parseOptionalNumber(card.dataset.grabs),
        categories: parseSearchFilterList(card.dataset.categoryIds || "").map((item) => item.toLocaleLowerCase()),
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

  const applyLocalFilters = () => {
    const filters = getActiveFilters();
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
    sizeMinInput,
    sizeMaxInput,
    filterIndexersInput,
    filterCategoryIdsInput,
    mediaTypeInput,
    ...includeKeywordInputs,
    ...excludeKeywordInputs,
  ].filter(Boolean);

  for (const input of localFilterInputs) {
    input.addEventListener("input", applyLocalFilters);
    input.addEventListener("change", applyLocalFilters);
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

  bindExclusiveQualitySelections(form, "quality_include_tokens", "quality_exclude_tokens", applyLocalFilters);

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
            }),
          });
          const payload = await response.json();
          if (!response.ok) {
            const errorMessage = String(payload?.error || "Could not save search view defaults.");
            throw new Error(errorMessage);
          }
          setSaveDefaultStatus("Saved. New searches will use this view and sort order.");
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

function initRuleForm(form) {
  const qualityOptions = parseJsonData(form.dataset.qualityOptions, []);
  const qualityPatternMap = buildQualityPatternMap(qualityOptions);
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
  };

  const applyQualityVisibility = (mediaType) => {
    form.querySelectorAll("[data-quality-option]").forEach((optionLabel) => {
      optionLabel.hidden = !mediaTypeMatchesScope(mediaType, parseElementMediaTypes(optionLabel));
    });

    form.querySelectorAll("[data-quality-group]").forEach((group) => {
      const groupMatches = mediaTypeMatchesScope(mediaType, parseElementMediaTypes(group));
      const visibleOptions = Array.from(group.querySelectorAll("[data-quality-option]")).some((option) => !option.hidden);
      group.hidden = !groupMatches || !visibleOptions;
    });
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
      patternPreview.value = derivePattern(form, qualityPatternMap);
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

  bindExclusiveQualitySelections(form, "quality_include_tokens", "quality_exclude_tokens", () => {
    syncQualityProfileValue();
    refreshDerivedFields();
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
