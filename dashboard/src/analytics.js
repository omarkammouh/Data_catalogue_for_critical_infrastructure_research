/* Optional aggregate visitor statistics. This is a public site identifier, never an API key. */
(() => {
  "use strict";
  const SITE_TOKEN = ""; // Cloudflare Web Analytics token from this site's installation snippet.
  const SITE_HOST = "omarkammouh.github.io";
  const SITE_PATH = "/Data_catalogue_for_critical_infrastructure_research/";

  // Local previews, downloaded copies and other hosts must not report visits.
  if (!/^[a-f0-9]{32}$/i.test(SITE_TOKEN) || location.protocol !== "https:" ||
      location.hostname !== SITE_HOST || !location.pathname.startsWith(SITE_PATH)) return;
  if (navigator.doNotTrack === "1" || navigator.globalPrivacyControl === true) return;
  if (document.getElementById("catalogue-analytics")) return;

  const script = document.createElement("script");
  script.id = "catalogue-analytics";
  script.type = "module";
  script.async = true;
  script.src = "https://static.cloudflareinsights.com/beacon.min.js";
  // Search and filter changes update the URL but must not count as new page visits.
  script.setAttribute("data-cf-beacon", JSON.stringify({ token: SITE_TOKEN, spa: false }));
  document.head.appendChild(script);

  const footer = document.querySelector(".foot");
  if (footer) {
    const notice = document.createElement("a");
    notice.href = "https://developers.cloudflare.com/web-analytics/about/";
    notice.textContent = "Usage statistics: Cloudflare";
    notice.target = "_blank";
    notice.rel = "noopener";
    footer.appendChild(notice);
  }
})();
