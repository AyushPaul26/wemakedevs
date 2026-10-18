const scenarios = {
  baseline: {
    count: "3",
    message:
      "Checkout, Atlas launch, and Billing reconciliation depend on the disrupted payment gateway.",
  },
  backup: {
    count: "1",
    message:
      "Checkout and Atlas have a documented backup path. Billing reconciliation still depends on the payment gateway.",
  },
};

const ripple = document.querySelector("#ripple-demo");
document.querySelector(".scenario-controls").hidden = false;
const scenarioButtons = [...document.querySelectorAll("button[data-scenario]")];
for (const button of scenarioButtons) {
  button.addEventListener("click", () => {
    const key = button.dataset.scenario;
    const scenario = scenarios[key];
    if (!scenario) return;
    ripple.dataset.scenario = key;
    for (const control of scenarioButtons)
      control.setAttribute("aria-pressed", String(control === button));
    document.querySelector("#exposed-count").textContent = scenario.count;
    document.querySelector("#scenario-result").textContent = scenario.message;
  });
}

const playButton = document.querySelector("#play-video");
playButton.hidden = false;
playButton.addEventListener("click", () => {
  const frame = document.createElement("iframe");
  frame.src =
    "https://www.youtube-nocookie.com/embed/bvLC4aGHssA?autoplay=1&rel=0";
  frame.title = "Relay — full product demonstration";
  frame.allow =
    "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
  frame.allowFullscreen = true;
  frame.referrerPolicy = "strict-origin-when-cross-origin";
  document.querySelector("#video-frame").replaceChildren(frame);
  frame.focus();
});

const copyButton = document.querySelector("#copy-link");
copyButton.hidden = false;
copyButton.addEventListener("click", async () => {
  const url = new URL(window.location.href);
  url.hash = "";
  url.search = "";
  const status = document.querySelector("#copy-status");
  const fallback = document.querySelector("#copy-fallback");
  try {
    if (!navigator.clipboard?.writeText)
      throw new Error("Clipboard unavailable");
    await navigator.clipboard.writeText(url.href);
    fallback.hidden = true;
    status.textContent = "Article link copied.";
  } catch {
    fallback.hidden = false;
    const field = document.querySelector("#article-url");
    field.value = url.href;
    field.focus();
    field.select();
    status.textContent = "Select and copy the address below.";
  }
});

const words = document
  .querySelector(".article-body")
  .textContent.trim()
  .split(/\s+/).length;
document.querySelector("#reading-time").textContent =
  `${Math.max(1, Math.ceil(words / 220))} min read`;

const tocLinks = [...document.querySelectorAll(".toc-link")];
const sections = tocLinks.map((link) => document.querySelector(link.hash));
let scheduled = false;
function updateReadingPosition() {
  const scrollable = document.documentElement.scrollHeight - window.innerHeight;
  const progress =
    scrollable > 0 ? Math.min(1, Math.max(0, window.scrollY / scrollable)) : 0;
  document.querySelector("#reading-progress").style.transform =
    `scaleX(${progress})`;
  let active = sections[0];
  for (const section of sections) {
    if (section.getBoundingClientRect().top <= window.innerHeight * 0.34)
      active = section;
  }
  for (const link of tocLinks) {
    const selected = link.hash === `#${active.id}`;
    link.classList.toggle("active", selected);
    if (selected) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  }
  scheduled = false;
}
function scheduleReadingUpdate() {
  if (!scheduled) {
    scheduled = true;
    requestAnimationFrame(updateReadingPosition);
  }
}
window.addEventListener("scroll", scheduleReadingUpdate, { passive: true });
window.addEventListener("resize", scheduleReadingUpdate);
window.addEventListener("load", scheduleReadingUpdate);
updateReadingPosition();
