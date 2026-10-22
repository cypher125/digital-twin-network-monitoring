"""Train the forecasting models on the twin-collected history (plan section 7.5).

    python manage.py train_models [--days 14] [--train-fraction 0.714] [--no-boosting] [--force]

Trains the full model (with same-time-yesterday features) when at least two days of
history exist, and always the short-history model. Each is saved to the model
registry with its metrics and promoted only if it is no worse than the active one.
The running engine picks up promoted models automatically.

Training uses a lot of memory on a 4 GB laptop: run it with the dashboard closed.
"""
import json
import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from digital_twin.prediction_engine import FeatureSpec, History, promote, save, train
from digital_twin.runtime import persistence
from digital_twin.runtime.forecasting import link_static


class Command(BaseCommand):
    help = "Train the Random Forest forecasting models on the stored monitoring history."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=float, default=14, help="days of history to use (most recent)")
        parser.add_argument("--train-fraction", type=float, default=10 / 14)
        parser.add_argument("--max-train-samples", type=int, default=200_000)
        parser.add_argument("--no-boosting", action="store_true", help="skip the gradient-boosting comparison")
        parser.add_argument("--force", action="store_true", help="promote even if worse than the active model")

    def handle(self, *args, **opts):
        twin = settings.TWIN
        cycle = twin["CYCLE_SECONDS"]
        _, model = persistence.build_model(twin["WARNING_THRESHOLD_PCT"], twin["CRITICAL_THRESHOLD_PCT"],
                                           twin["REFERENCE_BANDWIDTH_MBPS"])
        latest = persistence.latest_timestamp()
        if latest is None:
            raise CommandError("no monitoring history yet: run the engine or `manage.py backfill_history` first")
        link_ids = sorted(model.link_ends)
        times, util, errors = persistence.load_history(link_ids, cycle, latest - timedelta(days=opts["days"]))
        history = History(times, util, errors, link_static(model, link_ids), link_ids, cycle)
        days = len(times) * cycle / 86400
        self.stdout.write(f"History: {len(times)} cycles ({days:.1f} days) for {len(link_ids)} links")
        horizons = tuple(twin["HORIZONS_MINUTES"])
        kinds = [("short", FeatureSpec(cycle, horizons, full=False))]
        if days >= 2.0:
            kinds.insert(0, ("full", FeatureSpec(cycle, horizons, full=True)))
        else:
            self.stdout.write("Less than two days of history: training the short-history model only.")
        for kind, spec in kinds:
            began = time.perf_counter()
            result = train(history, spec, critical_pct=twin["CRITICAL_THRESHOLD_PCT"],
                           train_fraction=opts["train_fraction"], max_train_samples=opts["max_train_samples"],
                           with_boosting=not opts["no_boosting"])
            version = save(result, twin["MODEL_DIR"], link_ids, kind)
            _accepted, message = promote(twin["MODEL_DIR"], version, force=opts["force"])
            forest = result.metrics["random_forest"]
            persistence_mae = result.metrics["persistence"]
            self.stdout.write(self.style.SUCCESS(
                f"{kind} model {version} trained in {time.perf_counter() - began:.0f} s; {message}"))
            for h in map(str, horizons):
                clf = result.classification.get("random_forest_classifier", {}).get(h, {})
                self.stdout.write(
                    f"  +{h:>2} min: forest MAE {forest[h]['mae']:.2f} (persistence {persistence_mae[h]['mae']:.2f}); "
                    f"warning precision {clf.get('precision', float('nan')):.2f}, "
                    f"recall {clf.get('recall', float('nan')):.2f}")
            self.stdout.write(f"  warning threshold {result.rows['warning_threshold']} "
                              "(chosen on the last 20 % of the training period)")
            self.stdout.write(f"  sizes: {json.dumps(result.sizes)}")
