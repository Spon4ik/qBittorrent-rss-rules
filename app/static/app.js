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
  const ruleForm = document.querySelector("[data-rule-form]");
  if (ruleForm) {
    initRuleForm(ruleForm);
  }

  const settingsForm = document.querySelector("[data-settings-form]");
  if (settingsForm) {
    initSettingsForm(settingsForm);
  }
});
