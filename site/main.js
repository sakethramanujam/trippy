(() => {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Nav border on scroll
  const nav = document.querySelector('.nav');
  const onScroll = () => nav.classList.toggle('scrolled', scrollY > 8);
  addEventListener('scroll', onScroll, { passive: true }); onScroll();

  // Scroll reveal
  const els = document.querySelectorAll('.reveal');
  if (reduce || !('IntersectionObserver' in window)) els.forEach(e => e.classList.add('in'));
  else {
    const io = new IntersectionObserver(es => es.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
    }), { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    els.forEach(e => io.observe(e));
  }

  // Carousel: CSS scroll-snap + arrows, dots, autoplay
  const root = document.querySelector('.carousel');
  if (root) {
    const track = root.querySelector('.track');
    const slides = [...track.children];
    const dotsBox = root.querySelector('.dots');
    let current = 0, timer = null, paused = false, stopped = false;
    const dots = slides.map((s, i) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('aria-label', `Show screenshot ${i + 1}: ${s.querySelector('p').textContent}`);
      b.addEventListener('click', () => { stop(); go(i); });
      dotsBox.appendChild(b); return b;
    });
    const behavior = () => (reduce ? 'auto' : 'smooth');
    function go(i) {
      i = (i + slides.length) % slides.length;
      const s = slides[i];
      track.scrollTo({ left: s.offsetLeft - (track.clientWidth - s.offsetWidth) / 2, behavior: behavior() });
    }
    function mark(i) {
      current = i;
      slides.forEach((s, j) => { s.classList.toggle('active', j === i); });
      dots.forEach((d, j) => d.setAttribute('aria-current', j === i ? 'true' : 'false'));
    }
    // Active slide = the one nearest the track centre
    let raf = 0;
    track.addEventListener('scroll', () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const mid = track.scrollLeft + track.clientWidth / 2;
        let best = 0, bd = Infinity;
        slides.forEach((s, j) => { const d = Math.abs(s.offsetLeft + s.offsetWidth / 2 - mid); if (d < bd) { bd = d; best = j; } });
        if (best !== current || !slides[best].classList.contains('active')) mark(best);
      });
    }, { passive: true });
    root.querySelector('.prev').addEventListener('click', () => { stop(); go(current - 1); });
    root.querySelector('.next').addEventListener('click', () => { stop(); go(current + 1); });
    track.addEventListener('keydown', e => {
      if (e.key === 'ArrowRight') { e.preventDefault(); stop(); go(current + 1); }
      if (e.key === 'ArrowLeft') { e.preventDefault(); stop(); go(current - 1); }
    });
    // Autoplay: pauses on hover/focus, stops after the user interacts
    const stop = () => { stopped = true; clearInterval(timer); };
    const tick = () => { if (!paused && !stopped && !document.hidden && inView) go(current + 1); };
    let inView = false;
    new IntersectionObserver(([e]) => { inView = e.isIntersecting; }, { threshold: 0.4 }).observe(root);
    ['pointerdown', 'touchstart', 'wheel'].forEach(t => track.addEventListener(t, stop, { passive: true }));
    root.addEventListener('mouseenter', () => paused = true);
    root.addEventListener('mouseleave', () => paused = false);
    root.addEventListener('focusin', () => paused = true);
    root.addEventListener('focusout', () => paused = false);
    mark(0);
    if (!reduce) timer = setInterval(tick, 3200);
  }

  // Copy buttons
  document.querySelectorAll('.copy').forEach(b => b.addEventListener('click', async () => {
    const text = document.getElementById(b.dataset.copy).innerText.trim();
    try { await navigator.clipboard.writeText(text); b.textContent = 'Copied'; b.classList.add('done'); }
    catch { b.textContent = 'Press ⌘C'; const r = document.createRange(); r.selectNodeContents(document.getElementById(b.dataset.copy)); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }
    setTimeout(() => { b.textContent = 'Copy'; b.classList.remove('done'); }, 1800);
  }));
})();
