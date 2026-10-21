(() => {
  const page = document.querySelector('.my-assets-page');
  if (!page) return;

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const feature = page.querySelector('.assets-feature-video');
  const toggle = page.querySelector('.assets-preview-toggle');
  let featureVisible = false;
  let manualOverride = null;

  function updatePreviewLabel() {
    if (!feature || !toggle) return;
    const label = feature.paused ? 'Play preview' : 'Pause preview';
    toggle.textContent = label;
    toggle.setAttribute('aria-label', feature.paused ? 'Play reel preview' : 'Pause reel preview');
  }

  function syncFeature() {
    if (!feature) return;
    const shouldPlay = featureVisible && !document.hidden
      && (manualOverride === true || (manualOverride === null && !reducedMotion.matches));
    if (shouldPlay) feature.play().catch(() => {});
    else feature.pause();
    updatePreviewLabel();
  }

  if (feature) {
    const observer = new IntersectionObserver(entries => {
      featureVisible = entries[0].isIntersecting;
      syncFeature();
    }, { threshold: .25 });
    observer.observe(feature);
    feature.addEventListener('play', updatePreviewLabel);
    feature.addEventListener('pause', updatePreviewLabel);
    toggle?.addEventListener('click', () => {
      manualOverride = feature.paused;
      syncFeature();
    });
    reducedMotion.addEventListener('change', syncFeature);
    document.addEventListener('visibilitychange', syncFeature);
  }

  page.querySelectorAll('.studio-card-video').forEach(video => {
    const card = video.closest('.studio-asset-card');
    card.addEventListener('mouseenter', () => {
      if (!reducedMotion.matches && !document.hidden) video.play().catch(() => {});
    });
    card.addEventListener('mouseleave', () => {
      video.pause();
      video.currentTime = 0;
    });
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) video.pause();
    });
  });

  page.querySelectorAll('.copy-asset-link').forEach(button => {
    button.addEventListener('click', async () => {
      const label = button.textContent;
      try {
        await navigator.clipboard.writeText(button.dataset.url);
      } catch (error) {
        const tmp = document.createElement('input');
        tmp.value = button.dataset.url;
        document.body.appendChild(tmp);
        tmp.select();
        document.execCommand('copy');
        tmp.remove();
      }
      button.textContent = 'Copied!';
      setTimeout(() => { button.textContent = label; }, 1400);
    });
  });

  page.querySelectorAll('.publication-toggle').forEach(button => {
    button.addEventListener('click', async () => {
      const publish = button.dataset.publish === 'true';
      const label = button.textContent;
      button.disabled = true;
      button.textContent = publish ? 'Publishing…' : 'Unpublishing…';
      try {
        const response = await fetch(button.dataset.url, {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-CSRFToken': page.dataset.csrf},
          body: JSON.stringify({publish})
        });
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || 'Could not update this asset.');
        window.RSToast?.show(publish ? 'Published to the Library.' : 'Asset unpublished.', 'success');
        window.location.reload();
      } catch (error) {
        button.disabled = false;
        button.textContent = label;
        window.RSToast?.show(error.message || 'Could not update this asset.', 'error');
      }
    });
  });
})();
