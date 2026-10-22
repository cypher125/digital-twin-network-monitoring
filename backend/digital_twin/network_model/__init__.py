"""Network Model (Figure 3.2): the live virtual replica of the network as a NetworkX graph (FR1, G1)."""
from .model import INTERNET, NetworkModel, StatusChange, TwinDemand
from .routing import RoutedLoads, route_demands, routing_graph

__all__ = ["INTERNET", "NetworkModel", "RoutedLoads", "StatusChange", "TwinDemand", "route_demands",
           "routing_graph"]
