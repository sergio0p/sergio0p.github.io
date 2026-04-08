// KaTeX Custom Macros for Economics

const katexMacros = {
  // Calculus
  "\\diff": "\\dfrac{\\partial #1}{\\partial #2}",
  "\\sdiff": "\\tfrac{\\partial #1}{\\partial #2}",
  "\\ddiff": "\\dfrac{\\mathrm{d} #1}{\\mathrm{d} #2}",
  "\\sddiff": "\\tfrac{\\mathrm{d} #1}{\\mathrm{d} #2}",

  // Sets and brackets
  "\\set": "\\left\\{ #1 \\right\\}",
  "\\abs": "\\left| #1 \\right|",
  "\\norm": "\\left\\| #1 \\right\\|",
  "\\paren": "\\left( #1 \\right)",
  "\\bracket": "\\left[ #1 \\right]",

  // Optimization - use \operatorname* for proper \limits support
  "\\argmax": "\\operatorname*{arg\\,max}_{#1}",
  "\\argmin": "\\operatorname*{arg\\,min}_{#1}",
  // NOTE: \max and \min are KaTeX built-ins. Do NOT redefine them.
  // They already support \max_{x}, \max\limits_{x}, \substack, etc.

  // Economics notation
  "\\MU": "\\mathrm{MU}",
  "\\MR": "\\mathrm{MR}",
  "\\MC": "\\mathrm{MC}",
  "\\AC": "\\mathrm{AC}",
  "\\ATC": "\\mathrm{ATC}",
  "\\AVC": "\\mathrm{AVC}",
  "\\AFC": "\\mathrm{AFC}",
  "\\TR": "\\mathrm{TR}",
  "\\TC": "\\mathrm{TC}",
  "\\TVC": "\\mathrm{TVC}",
  "\\TFC": "\\mathrm{TFC}",
  "\\CS": "\\mathrm{CS}",
  "\\PS": "\\mathrm{PS}",
  "\\DWL": "\\mathrm{DWL}",

  // Common symbols
  "\\R": "\\mathbb{R}",
  "\\N": "\\mathbb{N}",
  "\\Z": "\\mathbb{Z}",
  "\\Q": "\\mathbb{Q}",
  "\\E": "\\mathbb{E}",
  "\\Var": "\\mathrm{Var}",
  "\\Cov": "\\mathrm{Cov}",

  // Greek shortcuts
  "\\eps": "\\varepsilon",
  "\\vphi": "\\varphi",

  // Text in math
  "\\st": "\\text{ s.t. }",
  "\\and": "\\text{ and }",
  "\\or": "\\text{ or }",
  "\\for": "\\text{ for }",
  "\\where": "\\text{ where }",

  // Euler font (approximation)
  "\\euler": "\\mathrm"
};

// Initialize KaTeX on page load
function initKaTeX() {
  renderMathInElement(document.body, {
    delimiters: [
      {left: '$$', right: '$$', display: true},
      {left: '$', right: '$', display: false},
      {left: '\\(', right: '\\)', display: false},
      {left: '\\[', right: '\\]', display: true}
    ],
    macros: katexMacros,
    throwOnError: false
  });
}

// Run when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initKaTeX);
} else {
  initKaTeX();
}
