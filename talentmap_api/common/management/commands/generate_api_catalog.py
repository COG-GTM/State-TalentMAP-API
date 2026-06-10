"""
Management command to auto-generate an API & domain-model catalog.

Usage:
    python manage.py generate_api_catalog                 # markdown to stdout
    python manage.py generate_api_catalog --format json   # JSON to stdout
    python manage.py generate_api_catalog -o catalog.md   # write to file
"""

import json
import sys
import textwrap
from collections import OrderedDict

from django.apps import apps
from django.core.management.base import BaseCommand
from django.urls import URLPattern, URLResolver, get_resolver


class Command(BaseCommand):
    help = "Generates a comprehensive catalog of all API endpoints, domain models, and permission requirements."

    def add_arguments(self, parser):
        parser.add_argument(
            "--format",
            choices=["markdown", "json"],
            default="markdown",
            help="Output format (default: markdown)",
        )
        parser.add_argument(
            "-o", "--output",
            type=str,
            default=None,
            help="Write output to file instead of stdout",
        )

    def handle(self, *args, **options):
        endpoints = self._collect_endpoints()
        models = self._collect_models()

        if options["format"] == "json":
            payload = {
                "api_endpoints": endpoints,
                "domain_models": models,
            }
            output = json.dumps(payload, indent=2, default=str)
        else:
            output = self._render_markdown(endpoints, models)

        if options["output"]:
            with open(options["output"], "w") as f:
                f.write(output)
            self.stdout.write(self.style.SUCCESS(f"Catalog written to {options['output']}"))
        else:
            self.stdout.write(output)

    # ------------------------------------------------------------------
    # Endpoint collection
    # ------------------------------------------------------------------

    def _collect_endpoints(self):
        resolver = get_resolver()
        endpoints = []
        self._walk_patterns(resolver.url_patterns, prefix="/", endpoints=endpoints)
        endpoints.sort(key=lambda e: e["path"])
        return endpoints

    def _walk_patterns(self, patterns, prefix, endpoints):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                new_prefix = prefix + self._clean_regex(pattern.pattern)
                self._walk_patterns(pattern.url_patterns, new_prefix, endpoints)
            elif isinstance(pattern, URLPattern):
                path = prefix + self._clean_regex(pattern.pattern)
                callback = pattern.callback
                view_class = getattr(callback, "cls", None) or getattr(callback, "view_class", None)

                entry = {
                    "path": path,
                    "name": pattern.name or "",
                    "view": self._view_name(callback, view_class),
                    "methods": self._extract_methods(callback, view_class),
                    "permissions": self._extract_permissions(view_class),
                    "authentication": self._extract_auth(view_class),
                }
                endpoints.append(entry)

    @staticmethod
    def _clean_regex(pattern):
        raw = str(pattern)
        if raw.startswith("^"):
            raw = raw[1:]
        if raw.endswith("$"):
            raw = raw[:-1]
        return raw

    @staticmethod
    def _view_name(callback, view_class):
        if view_class:
            return f"{view_class.__module__}.{view_class.__name__}"
        if hasattr(callback, "__name__"):
            return f"{callback.__module__}.{callback.__name__}"
        return str(callback)

    @staticmethod
    def _extract_methods(callback, view_class):
        # For ViewSet routes, DRF stores the HTTP-method-to-action mapping
        # in callback.actions (set by ViewSetMixin.as_view()).
        actions = getattr(callback, 'actions', None)
        if actions:
            return sorted([m.upper() for m in actions.keys()])
        if view_class:
            http_methods = {"get", "post", "put", "patch", "delete", "head", "options"}
            return sorted([m.upper() for m in http_methods if hasattr(view_class, m)])
        return []

    @staticmethod
    def _extract_permissions(view_class):
        if not view_class:
            return []
        perms = getattr(view_class, "permission_classes", [])
        result = []
        for p in perms:
            if callable(p) and not isinstance(p, type):
                inner = getattr(p, "__self__", None) or p
                result.append(type(inner).__name__ if hasattr(inner, "__name__") else str(p))
            elif isinstance(p, type):
                result.append(p.__name__)
            else:
                result.append(str(p))
        return result

    @staticmethod
    def _extract_auth(view_class):
        if not view_class:
            return []
        auth = getattr(view_class, "authentication_classes", None)
        if auth is None:
            return ["(default)"]
        return [a.__name__ if isinstance(a, type) else str(a) for a in auth]

    # ------------------------------------------------------------------
    # Model collection
    # ------------------------------------------------------------------

    def _collect_models(self):
        models = []
        for model in apps.get_models():
            if not model.__module__.startswith("talentmap_api"):
                continue
            fields = []
            for field in model._meta.get_fields():
                field_info = {
                    "name": field.name,
                    "type": type(field).__name__,
                }
                if hasattr(field, "help_text") and field.help_text:
                    field_info["description"] = str(field.help_text)
                if hasattr(field, "related_model") and field.related_model:
                    field_info["related_to"] = f"{field.related_model._meta.app_label}.{field.related_model.__name__}"
                fields.append(field_info)

            models.append({
                "app": model._meta.app_label,
                "name": model.__name__,
                "module": model.__module__,
                "doc": (model.__doc__ or "").strip(),
                "fields": fields,
                "has_history": any(f["type"] == "HistoricalRecords" or "historical" in f["name"].lower() for f in fields),
            })

        models.sort(key=lambda m: (m["app"], m["name"]))
        return models

    # ------------------------------------------------------------------
    # Markdown rendering
    # ------------------------------------------------------------------

    def _render_markdown(self, endpoints, models):
        lines = []

        lines.append("# TalentMAP API catalog")
        lines.append("")
        lines.append("Auto-generated inventory of every REST endpoint, domain model,")
        lines.append("and permission requirement in the TalentMAP API.")
        lines.append("")

        # Summary stats
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- **{len(endpoints)}** API endpoints")
        lines.append(f"- **{len(models)}** domain models across **{len(set(m['app'] for m in models))}** Django apps")
        auth_required = sum(1 for e in endpoints if any("Authenticated" in p for p in e["permissions"]))
        role_gated = sum(1 for e in endpoints if any("Group" in p for p in e["permissions"]))
        lines.append(f"- **{auth_required}** endpoints require authentication")
        lines.append(f"- **{role_gated}** endpoints are role-gated (group membership)")
        lines.append("")

        # Endpoint table
        lines.append("## API endpoints")
        lines.append("")
        lines.append("| Path | Methods | View | Permissions |")
        lines.append("|------|---------|------|-------------|")
        for ep in endpoints:
            methods = ", ".join(ep["methods"]) if ep["methods"] else "—"
            perms = ", ".join(ep["permissions"]) if ep["permissions"] else "—"
            view_short = ep["view"].split(".")[-1] if ep["view"] else "—"
            lines.append(f"| `{ep['path']}` | {methods} | {view_short} | {perms} |")
        lines.append("")

        # Permission matrix
        lines.append("## Permission matrix")
        lines.append("")
        perm_groups = {}
        for ep in endpoints:
            key = ", ".join(ep["permissions"]) if ep["permissions"] else "(none)"
            perm_groups.setdefault(key, []).append(ep["path"])
        for perm_set, paths in sorted(perm_groups.items()):
            lines.append(f"### {perm_set}")
            lines.append("")
            for p in paths:
                lines.append(f"- `{p}`")
            lines.append("")

        # Domain models
        lines.append("## Domain models")
        lines.append("")
        current_app = None
        for model in models:
            if model["app"] != current_app:
                current_app = model["app"]
                lines.append(f"### App: `{current_app}`")
                lines.append("")
            lines.append(f"#### {model['name']}")
            if model["doc"]:
                lines.append("")
                lines.append(f"> {model['doc'][:200]}")
            lines.append("")
            audit = "Yes" if model["has_history"] else "No"
            lines.append(f"- **Audit trail (simple_history):** {audit}")
            lines.append(f"- **Fields:** {len(model['fields'])}")
            lines.append("")

            # Field table
            lines.append("| Field | Type | Description | Related To |")
            lines.append("|-------|------|-------------|------------|")
            for f in model["fields"]:
                desc = f.get("description", "—")
                related = f.get("related_to", "—")
                lines.append(f"| `{f['name']}` | {f['type']} | {desc} | {related} |")
            lines.append("")

        return "\n".join(lines)
