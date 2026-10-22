"""Simulation console (UC3 "Create and run a simulation scenario", FR4, gap G3).

Scenarios are validated when they are created, using the same rules the engine
uses, so mistakes are reported straight away in plain language. Running a
scenario queues it; the Digital Twin Engine runs it on a detached copy of the
live model within about a second (D10). A scenario that has results cannot be
edited, so every result always matches the parameters that produced it.
"""
from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.audit import audit
from apps.accounts.roles import SYSTEM_USERNAME
from apps.twin.models import MonitoringRecord, RunStatus, SimulationResult, SimulationScenario
from digital_twin.simulation_engine import REGISTRY, ScenarioError, get

from ..permissions import IsSeniorOrReadOnly
from ..serializers import (
    ResultListSerializer,
    ResultSerializer,
    RunRequestSerializer,
    ScenarioSerializer,
)
from ..services import engine_status, latest_cycle, topology_model, validation_model


class ScenarioTypesView(APIView):
    """Every change type with its plain-language help and form fields, plus the choices the forms need."""

    def get(self, request):
        model = topology_model()
        devices = sorted(({"device_id": n, "name": data["name"], "device_type": data["device_type"],
                           "zone": data["configuration"].get("zone", "")} for n, data in model.graph.nodes(data=True)),
                         key=lambda d: d["name"])
        links = sorted(({"link_id": i, "label": model.link_label(i), "capacity_mbps": model.link(i)["capacity_mbps"],
                         "cost": round(model.link(i)["cost"], 3)} for i in model.link_ids()), key=lambda lk: lk["label"])
        return Response({
            "types": [spec.describe() for spec in REGISTRY.values()],
            "choices": {"devices": devices, "links": links, "zones": sorted(model.zones()),
                        "classes": engine_status().get("traffic_classes") or []},
        })


class ScenarioViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                      mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = ScenarioSerializer
    permission_classes = [IsSeniorOrReadOnly]

    def get_queryset(self):
        query = SimulationScenario.objects.select_related("created_by").order_by("-created_at")
        if self.request.query_params.get("include") != "recommendations":
            query = query.exclude(created_by__username=SYSTEM_USERNAME)
        if self.request.query_params.get("mine") == "1":
            query = query.filter(created_by=self.request.user)
        return query

    def _validated(self, scenario_type: str, parameters: dict) -> dict:
        try:
            return get(scenario_type).validate(dict(parameters or {}), validation_model())
        except ScenarioError as exc:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"parameters": [str(exc)]}) from exc

    def perform_create(self, serializer):
        data = serializer.validated_data
        clean = self._validated(data["scenario_type"], data.get("parameters", {}))
        scenario = serializer.save(created_by=self.request.user, parameters=clean)
        audit(self.request, "scenario_created", scenario=scenario.scenario_id, type=scenario.scenario_type)

    def _refuse_if_run(self, scenario):
        if scenario.results.exists():
            return Response({"detail": "This scenario already has results, so it cannot be changed. "
                                       "Make a copy instead."}, status=status.HTTP_409_CONFLICT)
        return None

    def update(self, request, *args, **kwargs):
        refusal = self._refuse_if_run(self.get_object())
        return refusal or super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        scenario = serializer.instance
        data = serializer.validated_data
        clean = self._validated(data.get("scenario_type", scenario.scenario_type),
                                data.get("parameters", scenario.parameters))
        serializer.save(parameters=clean)
        audit(self.request, "scenario_updated", scenario=scenario.scenario_id)

    def destroy(self, request, *args, **kwargs):
        scenario = self.get_object()
        refusal = self._refuse_if_run(scenario)
        if refusal:
            return refusal
        audit(request, "scenario_deleted", scenario=scenario.scenario_id, name=repr(scenario.scenario_name))
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def run(self, request, pk=None):
        scenario = self.get_object()
        options = RunRequestSerializer(data=request.data)
        options.is_valid(raise_exception=True)
        result = SimulationResult.objects.create(
            scenario=scenario, run_by=request.user, status=RunStatus.QUEUED,
            result_summary={"request": dict(options.validated_data)})
        audit(request, "simulation_requested", scenario=scenario.scenario_id, result=result.result_id,
              basis=options.validated_data["basis"])
        return Response(ResultListSerializer(result).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"])
    def copy(self, request, pk=None):
        original = self.get_object()
        clone = SimulationScenario.objects.create(
            created_by=request.user, scenario_name=f"{original.scenario_name} (copy)"[:120],
            scenario_type=original.scenario_type,
            parameters={k: v for k, v in original.parameters.items() if k != "trigger"})
        audit(request, "scenario_copied", source=original.scenario_id, scenario=clone.scenario_id)
        return Response(ScenarioSerializer(clone).data, status=status.HTTP_201_CREATED)


class ResultViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    def get_queryset(self):
        query = SimulationResult.objects.select_related("scenario", "run_by").order_by("-requested_at")
        scenario = self.request.query_params.get("scenario")
        if scenario:
            query = query.filter(scenario_id=scenario)
        if self.request.query_params.get("include") != "recommendations":
            query = query.filter(~Q(scenario__created_by__username=SYSTEM_USERNAME))
        return query

    def get_serializer_class(self):
        return ResultListSerializer if self.action == "list" else ResultSerializer

    @action(detail=True, methods=["get"])
    def compare(self, request, pk=None):
        """Compare the predicted state with the stored baseline (default) or with the live state now."""
        result = self.get_object()
        if result.status != RunStatus.COMPLETED:
            return Response({"detail": f"The run is {result.status}."}, status=status.HTTP_409_CONFLICT)
        against = request.query_params.get("against", "stored")
        links = (result.result_summary or {}).get("links", [])
        live = {}
        if against == "live":
            latest = latest_cycle()
            if latest is not None:
                live = dict(MonitoringRecord.objects.filter(timestamp=latest, link__isnull=False)
                            .values_list("link_id", "utilisation_pct"))
        rows = []
        for lk in links:
            baseline = live.get(lk["link_id"], lk.get("observed_pct")) if against == "live" else lk["before_pct"]
            after = lk["after_pct"]
            rows.append({"link_id": lk["link_id"], "label": lk["label"], "baseline_pct": baseline,
                         "after_pct": after, "change_pct": None if baseline is None else round(after - baseline, 2),
                         "status_after": lk["status_after"], "overloaded": lk["overloaded"]})
        rows.sort(key=lambda r: -abs(r["change_pct"] or 0))
        summary = result.result_summary or {}
        return Response({"result_id": result.result_id, "against": against, "basis": summary.get("basis"),
                         "summary": summary.get("summary"), "created": summary.get("created", []),
                         "relieved": summary.get("relieved", []), "links": rows})
