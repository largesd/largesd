    (function redirectToMergedPage() {
      const params = new URLSearchParams(window.location.search);
      params.set('tab', 'evidence');
      const query = params.toString();
      const destination = `audits.html${query ? `?${query}` : ''}${window.location.hash || ''}`;
      window.location.replace(destination);
    })();
