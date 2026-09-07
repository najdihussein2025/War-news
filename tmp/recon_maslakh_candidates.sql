-- Recreate MatchingService/VillageRepository.find_similar scoring for key mentions
CREATE OR REPLACE FUNCTION tmp_norm(t text, compact boolean DEFAULT false) RETURNS text AS $$
DECLARE
  s text;
BEGIN
  s := coalesce(t, '');
  s := regexp_replace(s, '[\u064b-\u0652\u0640]', '', 'g');
  s := translate(s, 'أإآٱة', 'ااااه');
  s := replace(s, 'ى', 'ي');
  s := btrim(btrim(s), '،.؛!؟"''');
  s := btrim(regexp_replace(s, '\s+', ' ', 'g'));
  IF compact THEN
    s := replace(s, ' ', '');
  END IF;
  RETURN s;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

WITH mentions AS (
  SELECT unnest(ARRAY['المسلخ', 'النبطية', 'مدينة النبطية', 'النبطية الفوقا']) AS mention
),
scored AS (
  SELECT
    m.mention,
    v.id,
    v.acs_name,
    v.ref_name_ar,
    v.caza_ar,
    v.mohafaza_ar,
    GREATEST(
      similarity(tmp_norm(v.acs_name), tmp_norm(m.mention)),
      similarity(tmp_norm(v.ref_name_ar), tmp_norm(m.mention)),
      similarity(tmp_norm(v.acs_name, true), tmp_norm(m.mention, true)),
      similarity(tmp_norm(v.ref_name_ar, true), tmp_norm(m.mention, true))
    ) AS score
  FROM mentions m
  CROSS JOIN villages v
  WHERE v.is_active IS TRUE
    AND (v.acs_name IS NOT NULL OR v.ref_name_ar IS NOT NULL)
)
SELECT mention, id, acs_name, ref_name_ar, caza_ar, mohafaza_ar, round(score::numeric, 6) AS score
FROM (
  SELECT *, row_number() OVER (PARTITION BY mention ORDER BY score DESC, id ASC) AS rn
  FROM scored
) t
WHERE rn <= 8
ORDER BY mention, rn;
