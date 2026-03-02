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
  const includeReleaseYear = Boolean(form.querySelector('input[name="include_release_year"]')?.checked);
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

function initRuleForm(form) {
  const qualityOptions = parseJsonData(form.dataset.qualityOptions, []);
  const qualityPatternMap = buildQualityPatternMap(qualityOptions);
  const qualityOptionOrder = Object.fromEntries(
    qualityOptions.filter((option) => option?.value).map((option, index) => [option.value, index])
  );
  let availableFilterProfiles = parseJsonData(form.dataset.availableFilterProfiles, []);
  let availableFilterProfileMap = buildFilterProfileMap(availableFilterProfiles);
  const categoryInput = form.querySelector('input[name="assigned_category"]');
  const savePathInput = form.querySelector('input[name="save_path"]');
  const patternPreview = form.querySelector("#pattern-preview");
  const metadataButton = form.querySelector("#metadata-lookup");
  const feedRefreshButton = form.querySelector("#feed-refresh");
  const feedSelectAllButton = form.querySelector("#feed-select-all");
  const feedClearAllButton = form.querySelector("#feed-clear-all");
  const feedSelect = form.querySelector("#feed-select");
  const qualityProfileInput = form.querySelector('input[name="quality_profile"]');
  const filterProfileSelect = form.querySelector("#filter-profile-select");
  const saveNewProfileButton = form.querySelector("#filter-profile-save-new");
  const overwriteProfileButton = form.querySelector("#filter-profile-overwrite");
  const releaseYearInput = form.querySelector('input[name="release_year"]');

  let categoryTouched = Boolean(categoryInput?.value.trim());
  let savePathTouched = Boolean(savePathInput?.value.trim());
  let releaseYearTouched = Boolean(releaseYearInput?.value.trim());

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

  const detectMatchingFilterProfileKey = () => {
    const currentProfile = buildCurrentProfilePayload();
    for (const profile of availableFilterProfiles) {
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
    const matchingProfile = availableFilterProfileMap[detectMatchingFilterProfileKey()];
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

  const rebuildFilterProfileSelect = (selectedKey) => {
    if (!filterProfileSelect) {
      return;
    }
    filterProfileSelect.innerHTML = "";
    const blankOption = document.createElement("option");
    blankOption.value = "";
    blankOption.textContent = "Current manual selection";
    filterProfileSelect.appendChild(blankOption);
    for (const profile of availableFilterProfiles) {
      const option = document.createElement("option");
      option.value = profile.key;
      option.textContent = profile.label;
      option.selected = profile.key === selectedKey;
      filterProfileSelect.appendChild(option);
    }
    if (!selectedKey) {
      filterProfileSelect.value = "";
    }
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
    rebuildFilterProfileSelect(body.profile_key || "");
    syncQualityProfileValue();
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
      ...buildCurrentProfilePayload(),
    });
  });

  form.querySelectorAll('input, select, textarea').forEach((element) => {
    element.addEventListener("input", refreshDerivedFields);
    element.addEventListener("change", refreshDerivedFields);
  });

  metadataButton?.addEventListener("click", async () => {
    const imdbField = form.querySelector('input[name="imdb_id"]');
    if (!imdbField || !imdbField.value.trim()) {
      window.alert("Enter an IMDb ID first.");
      return;
    }

    const response = await fetch("/api/metadata/lookup", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ imdb_id: imdbField.value.trim() }),
    });
    const payload = await response.json();
    if (!response.ok) {
      window.alert(payload.error || "Metadata lookup failed.");
      return;
    }

    const titleField = form.querySelector('input[name="normalized_title"]');
    const contentField = form.querySelector('input[name="content_name"]');
    const ruleNameField = form.querySelector('input[name="rule_name"]');
    const mediaField = form.querySelector('select[name="media_type"]');

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
    if (!feedSelect) {
      return;
    }
    Array.from(feedSelect.options).forEach((option) => {
      option.selected = true;
    });
  });

  feedClearAllButton?.addEventListener("click", () => {
    if (!feedSelect) {
      return;
    }
    Array.from(feedSelect.options).forEach((option) => {
      option.selected = false;
    });
  });

  feedRefreshButton?.addEventListener("click", async () => {
    const response = await fetch("/api/feeds/refresh", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) {
      window.alert(payload.error || "Feed refresh failed.");
      return;
    }
    if (!feedSelect) {
      return;
    }
    const selected = new Set(Array.from(feedSelect.selectedOptions).map((option) => option.value));
    feedSelect.innerHTML = "";
    for (const feed of payload.feeds || []) {
      const option = document.createElement("option");
      option.value = feed.url;
      option.textContent = feed.label;
      option.selected = selected.has(feed.url);
      feedSelect.appendChild(option);
    }
  });

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
  const ruleForm = document.querySelector("[data-rule-form]");
  if (ruleForm) {
    initRuleForm(ruleForm);
  }

  const settingsForm = document.querySelector("[data-settings-form]");
  if (settingsForm) {
    initSettingsForm(settingsForm);
  }
});
