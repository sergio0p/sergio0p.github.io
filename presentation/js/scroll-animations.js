// GSAP + ScrollTrigger Animation Setup

// Register ScrollTrigger plugin
gsap.registerPlugin(ScrollTrigger);

// Initialize all animations
function initAnimations() {
  // Basic reveal animations - elements fade in as they enter viewport
  initRevealAnimations();

  // Horizontal scroll sections
  initHorizontalScroll();

  // Step-by-step reveals within frames
  initStepReveals();

  // Overlay frames (Beamer \pause equivalent)
  initOverlayFrames();
}

// Reveal animations for .reveal elements
function initRevealAnimations() {
  gsap.utils.toArray('.reveal').forEach(elem => {
    gsap.fromTo(elem,
      {
        opacity: 0,
        y: 30
      },
      {
        opacity: 1,
        y: 0,
        duration: 0.6,
        ease: 'power2.out',
        scrollTrigger: {
          trigger: elem,
          start: 'top 85%',
          toggleActions: 'play none none reverse',
          invalidateOnRefresh: true
        }
      }
    );
  });
}

// Horizontal scroll sections
function initHorizontalScroll() {
  gsap.utils.toArray('.scroll-section').forEach(section => {
    const track = section.querySelector('.scroll-track');
    if (!track) return;

    const panels = track.querySelectorAll('.scroll-panel');
    if (panels.length === 0) return;

    // Calculate total scroll distance
    const totalWidth = track.scrollWidth - window.innerWidth;

    gsap.to(track, {
      x: () => -totalWidth,
      ease: 'none',
      scrollTrigger: {
        trigger: section,
        start: 'top top',
        end: () => `+=${track.scrollWidth - window.innerWidth}`,
        pin: true,
        scrub: 1,
        anticipatePin: 1,
        invalidateOnRefresh: true
      }
    });

    // Animate content within each panel as it comes into view
    panels.forEach((panel, i) => {
      const content = panel.querySelectorAll('.panel-content > *');
      if (content.length === 0) return;

      gsap.fromTo(content,
        { opacity: 0, y: 20 },
        {
          opacity: 1,
          y: 0,
          stagger: 0.1,
          duration: 0.5,
          ease: 'power2.out',
          scrollTrigger: {
            trigger: panel,
            containerAnimation: gsap.getById ? undefined : undefined,
            start: 'left 80%',
            toggleActions: 'play none none reverse',
            horizontal: true,
            invalidateOnRefresh: true
          }
        }
      );
    });
  });
}

// Step-by-step reveals within frames
function initStepReveals() {
  gsap.utils.toArray('.step-container').forEach(container => {
    const steps = container.querySelectorAll('.step');
    if (steps.length === 0) return;

    // Create a timeline for sequential reveals
    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: container,
        start: 'top 60%',
        end: 'bottom 40%',
        scrub: true,
        invalidateOnRefresh: true
      }
    });

    steps.forEach((step, i) => {
      tl.fromTo(step,
        { opacity: 0, x: -20 },
        { opacity: 1, x: 0, duration: 0.3 },
        i * 0.2
      );
    });
  });
}

// Utility: Animate graph drawing (for SVG paths)
function animateGraphPath(selector, duration = 2) {
  const paths = document.querySelectorAll(selector);
  paths.forEach(path => {
    const length = path.getTotalLength();
    gsap.set(path, {
      strokeDasharray: length,
      strokeDashoffset: length
    });
    gsap.to(path, {
      strokeDashoffset: 0,
      duration: duration,
      ease: 'power2.inOut',
      scrollTrigger: {
        trigger: path,
        start: 'top 80%',
        toggleActions: 'play none none reverse',
        invalidateOnRefresh: true
      }
    });
  });
}

// Utility: Typewriter effect for text
function typewriter(selector, speed = 50) {
  const elements = document.querySelectorAll(selector);
  elements.forEach(el => {
    const text = el.textContent;
    el.textContent = '';
    el.style.visibility = 'visible';

    let i = 0;
    ScrollTrigger.create({
      trigger: el,
      start: 'top 80%',
      invalidateOnRefresh: true,
      onEnter: () => {
        const interval = setInterval(() => {
          if (i < text.length) {
            el.textContent += text.charAt(i);
            i++;
          } else {
            clearInterval(interval);
          }
        }, speed);
      }
    });
  });
}

// Utility: Counter animation for numbers
function animateCounter(selector, duration = 2) {
  document.querySelectorAll(selector).forEach(el => {
    const target = parseFloat(el.dataset.target || el.textContent);
    const decimals = (el.dataset.decimals || 0);

    ScrollTrigger.create({
      trigger: el,
      start: 'top 80%',
      invalidateOnRefresh: true,
      onEnter: () => {
        gsap.to({ val: 0 }, {
          val: target,
          duration: duration,
          ease: 'power2.out',
          onUpdate: function() {
            el.textContent = this.targets()[0].val.toFixed(decimals);
          }
        });
      }
    });
  });
}

// Utility: Highlight/pulse effect
function pulseHighlight(selector) {
  document.querySelectorAll(selector).forEach(el => {
    gsap.to(el, {
      backgroundColor: 'rgba(249, 168, 37, 0.3)',
      duration: 0.3,
      repeat: 2,
      yoyo: true,
      scrollTrigger: {
        trigger: el,
        start: 'top 80%',
        invalidateOnRefresh: true
      }
    });
  });
}

// Overlay frames — pinned, progressive reveal (Beamer \pause equivalent)
function initOverlayFrames() {
  gsap.utils.toArray('.overlay-frame').forEach(frame => {
    const overlays = frame.querySelectorAll('.overlay');
    if (overlays.length === 0) return;

    // Reveal first overlay immediately
    overlays[0].classList.add('revealed');

    // Only pin/animate if there are items to reveal beyond the first
    if (overlays.length < 2) return;

    const count = overlays.length;

    ScrollTrigger.create({
      trigger: frame,
      start: 'top top',
      end: '+=' + (count * 50) + '%',
      pin: true,
      scrub: false,
      anticipatePin: 1,
      invalidateOnRefresh: true,
      onUpdate: self => {
        const step = Math.min(count - 1, Math.floor(self.progress * count));
        overlays.forEach((el, i) => {
          if (i <= step) {
            el.classList.add('revealed');
          } else {
            el.classList.remove('revealed');
          }
        });
      }
    });
  });
}

// Initialize on DOM ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initAnimations);
} else {
  initAnimations();
}

// Refresh ScrollTrigger on window resize and zoom
let lastWidth = window.innerWidth;
let lastHeight = window.innerHeight;
let resizeTimer;

function handleViewportChange() {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    const currentWidth = window.innerWidth;
    const currentHeight = window.innerHeight;

    // Detect if viewport dimensions changed (including zoom)
    if (currentWidth !== lastWidth || currentHeight !== lastHeight) {
      lastWidth = currentWidth;
      lastHeight = currentHeight;

      // Kill and refresh all ScrollTriggers to recalculate positions
      ScrollTrigger.refresh(true);
    }
  }, 250); // Debounce to avoid excessive recalculations
}

window.addEventListener('resize', handleViewportChange);
window.addEventListener('orientationchange', handleViewportChange);

// Also detect zoom via visualViewport API if available
if (window.visualViewport) {
  window.visualViewport.addEventListener('resize', handleViewportChange);
}

// Global navigation with Shift+Arrow keys
// Navigate between lecture sections regardless of scroll position
document.addEventListener('keydown', function(e) {
  // Shift+ArrowUp: go to index
  if (e.shiftKey && e.key === 'ArrowUp') {
    e.preventDefault();
    window.location.href = 'index.html';
    return;
  }
  // Only respond to Shift+Arrow (not plain arrows, which may be used in interactive graphs)
  if (!e.shiftKey) return;
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;

  let targetUrl = null;

  // Method 1: Check for meta tags (preferred)
  if (e.key === 'ArrowLeft') {
    const prevMeta = document.querySelector('meta[name="nav-prev"]');
    if (prevMeta) targetUrl = prevMeta.getAttribute('content');
  } else if (e.key === 'ArrowRight') {
    const nextMeta = document.querySelector('meta[name="nav-next"]');
    if (nextMeta) targetUrl = nextMeta.getAttribute('content');
  }

  // Method 2: Fallback to finding navigation links in the page
  if (!targetUrl) {
    const allLinks = document.querySelectorAll('a[href]');
    const navLinks = Array.from(allLinks).filter(link => {
      const href = link.getAttribute('href');
      return href && href.match(/\.html$/);
    });

    let targetLink = null;
    if (e.key === 'ArrowLeft') {
      targetLink = navLinks.find(link => link.textContent.includes('←'));
    } else if (e.key === 'ArrowRight') {
      targetLink = navLinks.find(link => link.textContent.includes('→'));
    }

    if (targetLink) {
      targetUrl = targetLink.getAttribute('href');
    }
  }

  if (targetUrl) {
    e.preventDefault();
    window.location.href = targetUrl;
  }
});
