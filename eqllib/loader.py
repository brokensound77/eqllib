from __future__ import unicode_literals

import os
from collections import defaultdict

import eql
import toml

from .attack import build_attack, tactics
from .normalization import Normalizer
from .schemas import Analytic, BaseNormalization, make_normalization_schema
from .utils import recursive_glob

current_dir = os.path.dirname(os.path.abspath(__file__))


class Configuration(object):
    _default = None

    def __init__(self, parent=None):  # type: (Configuration) -> None
        build_attack()
        self.coverage = {t['name']: defaultdict(list) for t in tactics}

        if parent:
            self.domain_schemas = parent.domain_schemas.copy()
            self.domains = parent.domains.copy()
            self.normalizers = parent.normalizers.copy()
            self.sources = parent.sources.copy()

            for tactic, techniques in parent.coverage.items():
                for technique, analytics in techniques.items():
                    self.coverage[tactic][technique] = analytics[:]

            self.analytics = parent.analytics[:]
            self.analytic_lookup = parent.analytic_lookup.copy()
        else:
            self.domain_schemas = {}
            self.domains = {}
            self.analytic_lookup = {}
            self.analytics = []
            self.sources = {}
            self.normalizers = {}

    def add_domain(self, domain):
        domain_schema = make_normalization_schema(domain)
        name = domain_schema.domain_name

        self.domains[name] = domain
        self.domain_schemas[name] = domain_schema

        # Create a normalization document for the domain (enums)
        source = {
            'name': name,
            'strict': False,
            'domain': name,
            'timestamp': {'field': 'timestamp', 'format': 'filetime'},
            'events': {},
            'fields': {'mapping': {}},
            'filter_query': False
        }

        for event_name, event_info in domain['events'].items():
            source['events'][event_name] = {'enum': {}, 'filter': 'event_type == "{}"'.format(event_name)}
            for name, options in event_info.get('enum', {}).items():
                source['events'][event_name]['enum'][name] = {}
                for option in options:
                    source['events'][event_name]['enum'][name][option] = '{} == "{}"'.format(name, option)

        self.add_source(source)

    def add_source(self, source):
        BaseNormalization.validate(source)
        domain_schema = self.domain_schemas[source['domain']]
        normalizer = Normalizer(domain_schema.validate(source))
        self.sources[source['name']] = source
        self.normalizers[source['name']] = normalizer

    def get_analytic(self, analytic_id):
        return self.analytic_lookup[analytic_id]

    def add_analytic(self, analytic):
        if isinstance(analytic, dict) and list(analytic.keys()) == ['analytic']:
            analytic = analytic['analytic']

        Analytic.validate(analytic)
        analytic['metadata']['_source'] = analytic['query']
        analytic = eql.ast.EqlAnalytic(metadata=analytic['metadata'], query=eql.parse_query(analytic['query']))
        self.analytic_lookup[analytic.id] = analytic
        self.analytics.append(analytic)

        for tactic in analytic.metadata.get('tactics', []):
            for technique in analytic.metadata.get('techniques', []):
                self.coverage[tactic][technique].append(analytic)

    @classmethod
    def default(cls):
        if not cls._default:
            self = cls.from_directories(os.path.join(current_dir, "domains"),
                                        os.path.join(current_dir, "sources"),
                                        None)
            cls._default = self
        return cls._default

    @classmethod
    def from_directories(cls, domain_dir, source_dir, analytics_dir, parent=None):
        self = cls(parent=parent)
        for domain_path in recursive_glob(domain_dir, "*.toml"):
            self.add_domain(toml.load(domain_path))

        for source_path in recursive_glob(source_dir, "*.toml"):
            self.add_source(toml.load(source_path))

        for analytic in sorted(recursive_glob(analytics_dir, "*.toml")):
            self.add_analytic(toml.load(analytic))

        return self


