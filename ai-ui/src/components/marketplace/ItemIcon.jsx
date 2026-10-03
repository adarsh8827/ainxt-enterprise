// SPDX-License-Identifier: MIT
// CONTRACTS.md §7 / CONFIG_AND_PRODUCTS.md §7 item 9: icon_url is either
// "emoji:<char>" or "url:<same-origin path>"; null/empty renders a
// deterministic-per-namespace monogram -- never a broken image, never a
// generic placeholder glyph, never lucide-react.
import { useHost } from "./lib/context/HostContext";
import { LIGHT_TOKENS } from "./lib/theme";
function hashString(input) {
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    hash = hash * 31 + input.charCodeAt(i) >>> 0;
  }
  return hash;
}
export function ItemIcon({
  iconUrl,
  namespace,
  displayName,
  size = 40
}) {
  const dims = {
    width: size,
    height: size
  };
  if (iconUrl?.startsWith("emoji:")) {
    const emoji = iconUrl.slice("emoji:".length);
    return <span data-testid="item-icon-emoji" className="flex items-center justify-center flex-shrink-0 rounded-md bg-gray-50" style={{
      ...dims,
      fontSize: size * 0.55
    }} aria-hidden="true">
        {emoji}
      </span>;
  }
  if (iconUrl?.startsWith("url:")) {
    const src = iconUrl.slice("url:".length);
    return <img data-testid="item-icon-url" src={src} alt="" className="flex-shrink-0 rounded-md object-cover" style={dims} />;
  }
  const {
    color,
    text
  } = useMonogramColor(namespace);
  const letter = (displayName.trim()[0] ?? "?").toUpperCase();
  return <span data-testid="item-icon-monogram" className="flex items-center justify-center flex-shrink-0 rounded-md font-bold" style={{
    ...dims,
    background: color,
    color: text,
    fontSize: size * 0.45
  }} aria-hidden="true">
      {letter}
    </span>;
}
function useMonogramColor(namespace) {
  // useHost() requires <HostProvider> -- ItemIcon can render in a Storybook
  // story without one, so fall back to LIGHT_TOKENS's palette rather than
  // throwing (this component has no other reason to require the full host
  // boundary just to pick a background color).
  let palette = LIGHT_TOKENS.color.monogramPalette;
  let text = LIGHT_TOKENS.color.monogramText;
  try {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const host = useHost();
    palette = host.theme?.color.monogramPalette ?? palette;
    text = host.theme?.color.monogramText ?? text;
  } catch {
    // no <HostProvider> in scope -- use the light-theme default above.
  }
  // palette is always non-empty (LIGHT_TOKENS/DARK_TOKENS each define 8
  // entries; a host-injected theme is expected to as well) -- the modulo
  // index is always in range, so this never actually falls through to a
  // literal color. No hardcoded hex fallback (this package's own rule):
  // if a host somehow injects an empty palette, that's a real theme bug
  // to surface, not one to silently paper over here.
  const index = hashString(namespace) % palette.length;
  const color = palette[index] ?? palette[0];
  if (color === undefined) throw new Error("ItemIcon: theme.color.monogramPalette must not be empty");
  return {
    color,
    text
  };
}