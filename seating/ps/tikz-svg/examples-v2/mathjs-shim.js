/**
 * Back-compat re-export. The shim moved into the library proper
 * (src-v2/core/mathjs-shim.js) so production code doesn't depend on the
 * examples directory. Example pages' importmaps still resolve here.
 */
export { compile, evaluate, parse, pi, e, default } from '../src-v2/core/mathjs-shim.js';
