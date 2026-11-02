/*
 * Public runtime configuration for the ontology agent.
 *
 * NEVER put an LLM key or any other secret in this file. GitHub Pages serves
 * every file in this repository to every visitor, so a key placed here would
 * be public immediately.
 *
 * Leave `apiBase` empty when the page is served by the agent backend itself
 * (for example `make agent` -> http://127.0.0.1:8000/). For the GitHub Pages
 * deployment, set it to the public URL of the separately deployed backend:
 *
 *   window.ASHD_AGENT_CONFIG = Object.freeze({
 *     apiBase: "https://ashare-ontology-agent.onrender.com"
 *   });
 *
 * `apiBase` is a public endpoint, not a credential. The backend reads
 * LLM_API_KEY from its own environment variables.
 */
window.ASHD_AGENT_CONFIG = Object.freeze({
  apiBase: "",
});
