/** The theme set before the first paint, in the page head (no React here: the root layout,
 * a server component, imports it), so a dark page never flashes light. */
export const THEME_KEY = "icpac-theme";

export const THEME_SCRIPT = `try{var t=localStorage.getItem("${THEME_KEY}");if(t!=="light"&&t!=="dark")t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";document.documentElement.dataset.theme=t}catch(e){}`;
