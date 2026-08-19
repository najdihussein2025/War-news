from __future__ import annotations

from app.news.models.incident_detail import IncidentDetail
from app.news.services.category_mapper import _safe_add


def recompute_detail_rollups(detail: IncidentDetail) -> None:
    """Recompute automated incident_details columns from their source sub-fields."""
    detail.la_td = _safe_add(detail.lam_d, detail.laf_d)
    detail.la_ti = _safe_add(detail.lam_i, detail.laf_i)
    detail.un_td = _safe_add(detail.unm_d, detail.unf_d)
    detail.un_ti = _safe_add(detail.unm_i, detail.unf_i)
    detail.muni_td = _safe_add(detail.munim_d, detail.munif_d)
    detail.muni_ti = _safe_add(detail.munim_i, detail.munif_i)
    detail.hosd = _safe_add(detail.hosm_d, detail.hosf_d)
    detail.hosi = _safe_add(detail.hosm_i, detail.hosf_i)
    detail.hcd = _safe_add(detail.hcm_d, detail.hcf_d)
    detail.hci = _safe_add(detail.hcm_i, detail.hcf_i)
    detail.pressd = _safe_add(detail.pressm_d, detail.pressf_d)
    detail.pressi = _safe_add(detail.pressm_i, detail.pressf_i)
    detail.gbd = _safe_add(detail.gbm_d, detail.gbf_d)
    detail.gbi = _safe_add(detail.gbm_i, detail.gbf_i)
    detail.card = _safe_add(detail.carm_d, detail.carf_d, detail.carc_d)
    detail.cari = _safe_add(detail.carm_i, detail.carf_i, detail.carc_i)

    construction_flags = (
        detail.excavator,
        detail.bulldozer,
        detail.camion,
        detail.bobcat,
        detail.tracteur,
    )
    if detail.con_veh or any(construction_flags):
        total_con = sum(1 for flag in construction_flags if flag)
        detail.total_con = total_con or None
    else:
        detail.total_con = None
