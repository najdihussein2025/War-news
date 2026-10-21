const DIACRITICS = /[\u064B-\u065F\u0670\u06D6-\u06ED\u0640]/u;

const canonicalArabicCharacter = (character: string) => {
  if (/[إأآٱ]/u.test(character)) return "ا";
  if (character === "ى") return "ي";
  if (character === "ة") return "ه";
  return character;
};

const normalizeWithSourceEnds = (text: string) => {
  let normalized = "";
  const sourceEnds: number[] = [];
  let offset = 0;

  for (const character of text) {
    offset += character.length;
    for (const part of character.normalize("NFKD")) {
      if (DIACRITICS.test(part)) {
        if (sourceEnds.length) sourceEnds[sourceEnds.length - 1] = offset;
        continue;
      }
      normalized += canonicalArabicCharacter(part);
      sourceEnds.push(offset);
    }
  }

  return { normalized, sourceEnds };
};

// Keep this registry deliberately small and display-only. Persisted/API text remains intact.
const REGISTERED_SOURCE_HEADER = /^(?:[\s«»"'|:—–-])*(?:صفحه\s*)?الاعلامي\s+الشهيد\s+علي\s+شعيب(?:[\s«»"'|:—–-])*/u;

export const stripRegisteredSourceHeader = (text: string) => {
  const { normalized, sourceEnds } = normalizeWithSourceEnds(text);
  const match = normalized.match(REGISTERED_SOURCE_HEADER);
  if (!match?.[0].length) return text;

  return text.slice(sourceEnds[match[0].length - 1]).trimStart();
};
