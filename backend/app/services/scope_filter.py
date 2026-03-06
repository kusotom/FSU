from sqlalchemy import false, or_


class ScopeFilterBuilder:
    @staticmethod
    def build_site_condition(model, access):
        if access.can_global_read:
            return None

        conditions = []
        if access.site_ids:
            conditions.append(model.id.in_(access.site_ids))
        if access.regions:
            conditions.append(model.region.in_(access.regions))
        if access.tenant_ids and hasattr(model, "tenant_id"):
            conditions.append(model.tenant_id.in_(access.tenant_ids))

        if not conditions:
            return false()
        return or_(*conditions)
