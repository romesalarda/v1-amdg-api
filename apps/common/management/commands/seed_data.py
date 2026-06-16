"""
Management command to seed reference data for staging and production environments.

Usage:
  python manage.py seed_data              # Staging: all reference data + dummy users
  python manage.py seed_data --production # Production: all reference data, no dummy users
"""

from django.core.management.base import BaseCommand
from django.db import transaction


# ---------------------------------------------------------------------------
# Location hierarchy definition
# ---------------------------------------------------------------------------
#
# Structure:  CountryLocation -> ClusterLocation -> ChapterLocation -> AreaLocation
#
# Each 'area_code' must be globally unique (DB constraint).
# Cluster codes must also be globally unique.
#
LOCATION_DATA = [
    # -----------------------------------------------------------------------
    # United Kingdom
    # -----------------------------------------------------------------------
    {
        'country': 'GB',
        'general_sector': 'EUROPE',
        'specific_sector': 'WEST_EUROPE',
        'clusters': [
            {
                'cluster_code': 'A',
                'cluster_name': 'Cluster A',
                'chapters': [
                    {
                        'chapter_name': 'East Anglia',
                        'areas': [
                            {'area_name': 'Ipswich',  'area_code': 'IPS'},
                            {'area_name': 'Norwich',  'area_code': 'NOR'},
                        ],
                    },
                ],
            },
            {
                'cluster_code': 'B',
                'cluster_name': 'Cluster B',
                'chapters': [
                    {
                        'chapter_name': 'Northwest',
                        'areas': [
                            {'area_name': 'Liverpool',  'area_code': 'LIV'},
                            {'area_name': 'Manchester', 'area_code': 'MAN'},
                        ],
                    },
                    {
                        'chapter_name': 'Yorkshire',
                        'areas': [
                            {'area_name': 'York',  'area_code': 'YOR'},
                            {'area_name': 'Leeds', 'area_code': 'LEE'},
                        ],
                    },
                ],
            },
            {
                'cluster_code': 'C',
                'cluster_name': 'Cluster C',
                'chapters': [
                    {
                        'chapter_name': 'Wales',
                        'areas': [
                            {'area_name': 'Cardiff',  'area_code': 'CAR'},
                            {'area_name': 'Swansea',  'area_code': 'SWA'},
                        ],
                    },
                    {
                        'chapter_name': 'Gloucester & Bristol',
                        'areas': [
                            {'area_name': 'Gloucester', 'area_code': 'GLO'},
                            {'area_name': 'Bristol',    'area_code': 'BRI'},
                        ],
                    },
                    {
                        'chapter_name': 'Taunton Torbay Yeovil',
                        'areas': [
                            {'area_name': 'Taunton', 'area_code': 'TAU'},
                            {'area_name': 'Yeovil',  'area_code': 'YEO'},
                            {'area_name': 'Torbay',  'area_code': 'TBY'},
                        ],
                    },
                ],
            },
            {
                'cluster_code': 'D',
                'cluster_name': 'Cluster D',
                'chapters': [
                    {
                        'chapter_name': 'Southeast',
                        'areas': [
                            {'area_name': 'Frimley',                  'area_code': 'FRI'},
                            {'area_name': 'Oxford',                   'area_code': 'OXF'},
                            {'area_name': 'Horsham',                  'area_code': 'HOR'},
                            {'area_name': 'Worthing',                 'area_code': 'WOR'},
                            {'area_name': 'Southampton & Portsmouth', 'area_code': 'SHP'},
                        ],
                    },
                    {
                        'chapter_name': 'East Midlands',
                        'areas': [
                            {'area_name': 'Luton',         'area_code': 'LUT'},
                            {'area_name': 'Milton Keynes', 'area_code': 'MKY'},
                        ],
                    },
                    {
                        'chapter_name': 'West Midlands',
                        'areas': [
                            {'area_name': 'Birmingham', 'area_code': 'BIR'},
                        ],
                    },
                ],
            },
            {
                'cluster_code': 'E',
                'cluster_name': 'Cluster E',
                'chapters': [
                    {
                        'chapter_name': 'Northeast',
                        'areas': [
                            {'area_name': 'Newcastle', 'area_code': 'NEW'},
                        ],
                    },
                    {
                        'chapter_name': 'Scotland',
                        'areas': [
                            {'area_name': 'Edinburgh', 'area_code': 'EDI'},
                            {'area_name': 'Glasgow',   'area_code': 'GLA'},
                            {'area_name': 'Dundee',    'area_code': 'DUN'},
                        ],
                    },
                ],
            },
        ],
    },

    # -----------------------------------------------------------------------
    # France
    # -----------------------------------------------------------------------
    {
        'country': 'FR',
        'general_sector': 'EUROPE',
        'specific_sector': 'WEST_EUROPE',
        'clusters': [
            {
                'cluster_code': 'FA',
                'cluster_name': 'France A',
                'chapters': [
                    {
                        'chapter_name': 'Paris Region',
                        'areas': [
                            {'area_name': 'Paris',       'area_code': 'PAR'},
                            {'area_name': 'Versailles',  'area_code': 'VRS'},
                            {'area_name': 'Saint-Denis', 'area_code': 'SDN'},
                        ],
                    },
                    {
                        'chapter_name': 'Normandie',
                        'areas': [
                            {'area_name': 'Rouen', 'area_code': 'ROU'},
                            {'area_name': 'Caen',  'area_code': 'CAE'},
                        ],
                    },
                ],
            },
            {
                'cluster_code': 'FB',
                'cluster_name': 'France B',
                'chapters': [
                    {
                        'chapter_name': 'Southeast France',
                        'areas': [
                            {'area_name': 'Lyon',     'area_code': 'LYO'},
                            {'area_name': 'Grenoble', 'area_code': 'GRE'},
                        ],
                    },
                    {
                        'chapter_name': 'South France',
                        'areas': [
                            {'area_name': 'Marseille',   'area_code': 'MRS'},
                            {'area_name': 'Nice',        'area_code': 'NIC'},
                            {'area_name': 'Montpellier', 'area_code': 'MTP'},
                        ],
                    },
                ],
            },
        ],
    },

    # -----------------------------------------------------------------------
    # Italy
    # -----------------------------------------------------------------------
    {
        'country': 'IT',
        'general_sector': 'EUROPE',
        'specific_sector': 'SOUTH_EUROPE',
        'clusters': [
            {
                'cluster_code': 'IA',
                'cluster_name': 'Italy A',
                'chapters': [
                    {
                        'chapter_name': 'North Italy',
                        'areas': [
                            {'area_name': 'Milan', 'area_code': 'MLN'},
                            {'area_name': 'Turin', 'area_code': 'TRN'},
                            {'area_name': 'Genoa', 'area_code': 'GEN'},
                        ],
                    },
                    {
                        'chapter_name': 'Northeast Italy',
                        'areas': [
                            {'area_name': 'Venice', 'area_code': 'VCE'},
                            {'area_name': 'Verona', 'area_code': 'VRO'},
                        ],
                    },
                ],
            },
            {
                'cluster_code': 'IB',
                'cluster_name': 'Italy B',
                'chapters': [
                    {
                        'chapter_name': 'Central Italy',
                        'areas': [
                            {'area_name': 'Rome',     'area_code': 'ROM'},
                            {'area_name': 'Florence', 'area_code': 'FLO'},
                        ],
                    },
                    {
                        'chapter_name': 'South Italy',
                        'areas': [
                            {'area_name': 'Naples',  'area_code': 'NAP'},
                            {'area_name': 'Palermo', 'area_code': 'PAL'},
                        ],
                    },
                ],
            },
        ],
    },
]


class Command(BaseCommand):
    help = 'Seeds reference data for staging/production environments'

    def add_arguments(self, parser):
        parser.add_argument(
            '--production',
            action='store_true',
            help='Production mode: skips dummy user creation',
        )

    def handle(self, *args, **options):
        is_production = options['production']

        with transaction.atomic():
            self._seed_locations()
            self._seed_organisation()
            self._seed_medical_conditions()
            self._seed_accessibility_requirements()
            self._seed_dietary_requirements()
            self._seed_product_categories()
            self._seed_event_roles()
            self._seed_event_types()

            if not is_production:
                self._seed_dummy_users()

        mode = 'production' if is_production else 'staging'
        self.stdout.write(self.style.SUCCESS(f'\nSeeding complete ({mode} mode).'))

    # -----------------------------------------------------------------------
    # Locations
    # -----------------------------------------------------------------------

    def _seed_locations(self):
        from apps.locations.models import (
            CountryLocation, ClusterLocation, ChapterLocation, AreaLocation,
        )

        self.stdout.write('\nLocations:')

        for country_data in LOCATION_DATA:
            country, created = CountryLocation.objects.get_or_create(
                country=country_data['country'],
                defaults={
                    'general_sector': country_data['general_sector'],
                    'specific_sector': country_data['specific_sector'],
                    'active': True,
                },
            )
            self._log('CountryLocation', country_data['country'], created)

            for cluster_data in country_data['clusters']:
                cluster, created = ClusterLocation.objects.get_or_create(
                    cluster_code=cluster_data['cluster_code'],
                    defaults={
                        'cluster_name': cluster_data['cluster_name'],
                        'country': country,
                        'active': True,
                    },
                )
                self._log('  ClusterLocation', cluster_data['cluster_code'], created)

                for chapter_data in cluster_data['chapters']:
                    # chapter_name is .title()-ified by the model's save()
                    chapter, created = ChapterLocation.objects.get_or_create(
                        chapter_name=chapter_data['chapter_name'].strip().title(),
                        cluster=cluster,
                        defaults={'active': True},
                    )
                    self._log('    ChapterLocation', chapter_data['chapter_name'], created)

                    for area_data in chapter_data['areas']:
                        area, created = AreaLocation.objects.get_or_create(
                            area_code=area_data['area_code'],
                            defaults={
                                'area_name': area_data['area_name'],
                                'chapter': chapter,
                                'active': True,
                            },
                        )
                        self._log('      AreaLocation', area_data['area_name'], created)

    # -----------------------------------------------------------------------
    # Organisation
    # -----------------------------------------------------------------------

    def _seed_organisation(self):
        from apps.organisations.models import Organisation

        self.stdout.write('\nOrganisation:')

        org, created = Organisation.objects.get_or_create(
            title='AMDG Community',
            defaults={
                'description': 'Ad Majorem Dei Gloriam – primary community organisation.',
                'short_description': 'AMDG Community Organisation',
                'verified': True,
            },
        )
        self._log('Organisation', 'AMDG Community', created)

    # -----------------------------------------------------------------------
    # Medical Conditions
    # -----------------------------------------------------------------------

    def _seed_medical_conditions(self):
        from apps.attendee.models import MedicalCondition

        self.stdout.write('\nMedical Conditions:')

        conditions = [
            {
                'code': 'ASTHMA',
                'label': 'Asthma',
                'description': 'Chronic respiratory condition causing breathing difficulties.',
            },
            {
                'code': 'DIABETES_T1',
                'label': 'Type 1 Diabetes',
                'description': 'Insulin-dependent diabetes mellitus.',
            },
            {
                'code': 'DIABETES_T2',
                'label': 'Type 2 Diabetes',
                'description': 'Non-insulin-dependent diabetes mellitus.',
            },
            {
                'code': 'EPILEPSY',
                'label': 'Epilepsy',
                'description': 'Neurological disorder involving recurrent seizures.',
            },
            {
                'code': 'HEART_COND',
                'label': 'Heart Condition',
                'description': 'General cardiac conditions requiring monitoring or medication.',
            },
            {
                'code': 'HYPERTENS',
                'label': 'Hypertension',
                'description': 'High blood pressure requiring management.',
            },
            {
                'code': 'ANAPHYLAX',
                'label': 'Anaphylaxis Risk',
                'description': 'Severe allergic reaction risk; may require EpiPen or equivalent.',
            },
            {
                'code': 'PEANUT_ALL',
                'label': 'Peanut Allergy',
                'description': 'Allergy to peanuts or peanut-derived products.',
            },
            {
                'code': 'MIGRAINE',
                'label': 'Chronic Migraine',
                'description': 'Recurring severe headaches that may require quiet rest.',
            },
            {
                'code': 'AUTISM',
                'label': 'Autism Spectrum Disorder',
                'description': 'Neurodevelopmental condition; may affect sensory needs and communication.',
            },
            {
                'code': 'ADHD',
                'label': 'ADHD',
                'description': 'Attention deficit hyperactivity disorder.',
            },
            {
                'code': 'MENTAL_HLT',
                'label': 'Mental Health Condition',
                'description': 'General mental health conditions requiring pastoral support.',
            },
            {
                'code': 'MOBILITY_IM',
                'label': 'Mobility Impairment',
                'description': 'Physical condition limiting mobility or requiring assistance.',
            },
            {
                'code': 'COELIAC',
                'label': 'Coeliac Disease',
                'description': 'Autoimmune condition triggered by gluten ingestion.',
            },
            {
                'code': 'PREGNANCY',
                'label': 'Pregnancy',
                'description': 'Currently pregnant; may require specific accommodations.',
            },
            {
                'code': 'OTHER',
                'label': 'Other Medical Condition',
                'description': 'Any other medical condition not listed; see personal notes.',
            }
        ]

        for data in conditions:
            obj, created = MedicalCondition.objects.get_or_create(
                code=data['code'],
                defaults={
                    'label': data['label'],
                    'description': data['description'],
                    'active': True,
                },
            )
            self._log('MedicalCondition', data['label'], created)

    # -----------------------------------------------------------------------
    # Accessibility Requirements
    # -----------------------------------------------------------------------

    def _seed_accessibility_requirements(self):
        from apps.attendee.models import AccessibilityRequirement

        self.stdout.write('\nAccessibility Requirements:')

        requirements = [
            {
                'code': 'WHEELCHAIR',
                'label': 'Wheelchair Access',
                'description': 'Requires fully wheelchair-accessible venue and routes.',
            },
            {
                'code': 'HEARING_LP',
                'label': 'Hearing Loop',
                'description': 'Requires hearing induction loop or FM system.',
            },
            {
                'code': 'BSL_INTERP',
                'label': 'BSL Interpreter',
                'description': 'Requires a British Sign Language interpreter.',
            },
            {
                'code': 'VISUAL_AID',
                'label': 'Visual Aid Support',
                'description': 'Requires large-print materials or screen-reader-accessible content.',
            },
            {
                'code': 'QUIET_SPCE',
                'label': 'Quiet Space',
                'description': 'Requires access to a quiet or sensory-safe area.',
            },
            {
                'code': 'STEP_FREE',
                'label': 'Step-Free Access',
                'description': 'Requires step-free access to all event areas.',
            },
            {
                'code': 'PERS_CARE',
                'label': 'Personal Care Assistance',
                'description': 'Attending with a personal care assistant.',
            },
            {
                'code': 'DIET_PREP',
                'label': 'Dietary Preparation Space',
                'description': 'Requires access to food preparation space for medical dietary needs.',
            },
            {
                'code': 'PRAYER_SPC',
                'label': 'Prayer / Reflection Space',
                'description': 'Requires access to a dedicated prayer or reflection room.',
            },
            {
                'code': 'SEATING',
                'label': 'Seating Preference',
                'description': 'Requires specific seating (e.g. aisle seat, front row, near exit).',
            },
            {
                'code': 'OTHER',
                'label': 'Other Accessibility Requirement',
                'description': 'Any other accessibility requirement not listed; see personal notes.',
            },
        ]

        for data in requirements:
            obj, created = AccessibilityRequirement.objects.get_or_create(
                code=data['code'],
                defaults={
                    'label': data['label'],
                    'description': data['description'],
                    'active': True,
                },
            )
            self._log('AccessibilityRequirement', data['label'], created)

    # -----------------------------------------------------------------------
    # Dietary Requirements
    # -----------------------------------------------------------------------

    def _seed_dietary_requirements(self):
        from apps.attendee.models import DietaryRequirement

        self.stdout.write('\nDietary Requirements:')

        requirements = [
            {
                'code': 'HALAL',
                'label': 'Halal',
                'description': 'Requires halal-certified food and drink.',
            },
            {
                'code': 'VEGETARIAN',
                'label': 'Vegetarian',
                'description': 'Does not eat meat or fish.',
            },
            {
                'code': 'VEGAN',
                'label': 'Vegan',
                'description': 'Does not consume any animal products.',
            },
            {
                'code': 'GLUTEN_FRE',
                'label': 'Gluten-Free',
                'description': 'Cannot consume gluten (wheat, barley, rye).',
            },
            {
                'code': 'LACTOSE_FR',
                'label': 'Lactose-Free',
                'description': 'Cannot consume dairy or lactose.',
            },
            {
                'code': 'NUT_FREE',
                'label': 'Nut-Free',
                'description': 'Allergy or intolerance to nuts.',
            },
            {
                'code': 'DIABETIC',
                'label': 'Diabetic Diet',
                'description': 'Requires low-sugar, diabetic-friendly meals.',
            },
            {
                'code': 'KOSHER',
                'label': 'Kosher',
                'description': 'Requires kosher-certified food.',
            },
            {
                'code': 'PESCATARIN',
                'label': 'Pescatarian',
                'description': 'Does not eat meat but eats fish.',
            },
            {
                'code': 'NO_PORK',
                'label': 'No Pork',
                'description': 'Does not consume pork or pork derivatives.',
            },
            {
                'code': 'LOW_SODIUM',
                'label': 'Low Sodium',
                'description': 'Requires low-salt meals for medical reasons.',
            },
            {
                'code': 'OTHER',
                'label': 'Other Dietary Need',
                'description': 'Other dietary requirement not listed; see personal notes.',
            },
        ]

        for data in requirements:
            obj, created = DietaryRequirement.objects.get_or_create(
                code=data['code'],
                defaults={
                    'label': data['label'],
                    'description': data['description'],
                    'active': True,
                },
            )
            self._log('DietaryRequirement', data['label'], created)

    # -----------------------------------------------------------------------
    # Product Categories
    # -----------------------------------------------------------------------

    def _seed_product_categories(self):
        from apps.products.models import ProductCategory

        self.stdout.write('\nProduct Categories:')

        categories = [
            # {'name': 'Tickets',        'description': 'Event registration and entry tickets.'},
            # {'name': 'Merchandise',    'description': 'AMDG branded clothing and merchandise.'},
            # {'name': 'Resources',      'description': 'Books, booklets, and printed materials.'},
            # {'name': 'Media',          'description': 'Audio, video, and digital media products.'},
            # {'name': 'Donations',      'description': 'Charitable donations and fundraising items.'},
            # {'name': 'Workshops',      'description': 'Workshop registration and session tickets.'},
            # {'name': 'Catering',       'description': 'Meals, snacks, and catering packages.'},
            # {'name': 'Accommodation',  'description': 'Overnight stay and accommodation packages.'},
            # {'name': 'Transport',      'description': 'Travel and transport packages.'},
            # {'name': 'Digital Access', 'description': 'Online streaming and digital event access.'},
            {"name": "T-shirts", "description": "Event branded t-shirts and apparel."},
            {"name": "Hoodies", "description": "Event branded hoodies and sweatshirts."},
            {"name": "Accessories", "description": "Event branded accessories such as hats, bags, and mugs."},
            {"name": "Posters", "description": "Event branded posters and prints."},
            {"name": "Stickers", "description": "Event branded stickers and decals."},
            {"name": "Books", "description": "Books and publications related to the event or organisation."},
            {"name": "Digital Downloads", "description": "Digital products such as e-books, music, or software."},
            {"name": "Tickets", "description": "Event registration and entry tickets."},
            {"name": "Shorts", "description": "Event branded shorts and casual wear."},
            {"name": "Socks", "description": "Event branded socks and footwear accessories."},
            {"name": "Water Bottles", "description": "Event branded reusable water bottles and drinkware."},
            {"name": "Trousers", "description": "Event branded trousers and pants."},
            {"name": "Jackets", "description": "Event branded jackets and outerwear."},
            {"name": "Sweatshirts", "description": "Event branded sweatshirts and pullovers."},
            {"name": "Caps", "description": "Event branded caps and headwear."},
            {"name": "Bags", "description": "Event branded bags, backpacks, and totes."},
            {"name": "Mugs", "description": "Event branded mugs and drinkware."},
            {"name": "Keychains", "description": "Event branded keychains and small accessories."},
            {"name": "Pins", "description": "Event branded pins and badges."},
            {"name": "Other Merchandise", "description": "Miscellaneous event branded merchandise and items."},
        ]

        for data in categories:
            obj, created = ProductCategory.objects.get_or_create(
                name=data['name'],
                defaults={'description': data['description']},
            )
            self._log('ProductCategory', data['name'], created)

    # -----------------------------------------------------------------------
    # Event Roles (Staff Roles)
    # -----------------------------------------------------------------------

    def _seed_event_roles(self):
        from apps.events.models import EventRole, EventRoleCategoryChoices

        self.stdout.write('\nEvent Roles:')

        roles = [
            # ADMINISTRATIVE
            {
                'code': 'EVT_MGR',
                'name': 'Event Manager',
                'description': 'Overall event management and coordination.',
                'category': EventRoleCategoryChoices.ADMINISTRATIVE,
            },
            {
                'code': 'REG_ADMIN',
                'name': 'Registration Administrator',
                'description': 'Manages attendee registration and check-in systems.',
                'category': EventRoleCategoryChoices.ADMINISTRATIVE,
            },
            {
                'code': 'FIN_ADMIN',
                'name': 'Finance Administrator',
                'description': 'Handles financial records, payments, and reporting.',
                'category': EventRoleCategoryChoices.ADMINISTRATIVE,
            },
            {
                'code': 'COMMS_LEAD',
                'name': 'Communications Lead',
                'description': 'Manages internal and external communications.',
                'category': EventRoleCategoryChoices.ADMINISTRATIVE,
            },

            # VOLUNTEER
            {
                'code': 'GEN_VOL',
                'name': 'General Volunteer',
                'description': 'General-purpose volunteer assisting across the event.',
                'category': EventRoleCategoryChoices.VOLUNTEER,
            },
            {
                'code': 'WELCOME_TM',
                'name': 'Welcome Team',
                'description': 'Greets and directs attendees on arrival.',
                'category': EventRoleCategoryChoices.VOLUNTEER,
            },
            {
                'code': 'STEWARD',
                'name': 'Steward',
                'description': 'Maintains order and assists with crowd management.',
                'category': EventRoleCategoryChoices.VOLUNTEER,
            },
            {
                'code': 'MEDIA_VOL',
                'name': 'Media Volunteer',
                'description': 'Photography, videography, and social media support.',
                'category': EventRoleCategoryChoices.VOLUNTEER,
            },

            # SPEAKER
            {
                'code': 'KEYNOTE',
                'name': 'Keynote Speaker',
                'description': 'Delivers the main keynote address or talk.',
                'category': EventRoleCategoryChoices.SPEAKER,
            },
            {
                'code': 'WRKSHP_SPK',
                'name': 'Workshop Speaker',
                'description': 'Leads a specific workshop or breakout session.',
                'category': EventRoleCategoryChoices.SPEAKER,
            },
            {
                'code': 'PANELLIST',
                'name': 'Panellist',
                'description': 'Participates in a panel discussion.',
                'category': EventRoleCategoryChoices.SPEAKER,
            },

            # COORDINATOR
            {
                'code': 'LOGISTICS',
                'name': 'Logistics Coordinator',
                'description': 'Coordinates venue, equipment, and setup logistics.',
                'category': EventRoleCategoryChoices.COORDINATOR,
            },
            {
                'code': 'PROG_COORD',
                'name': 'Programme Coordinator',
                'description': 'Manages the event schedule and programme flow.',
                'category': EventRoleCategoryChoices.COORDINATOR,
            },
            {
                'code': 'YOUTH_CORD',
                'name': 'Youth Coordinator',
                'description': "Oversees youth programming and children's activities.",
                'category': EventRoleCategoryChoices.COORDINATOR,
            },
            {
                'code': 'TECH_COORD',
                'name': 'Technical Coordinator',
                'description': 'Manages AV, IT, and technical infrastructure.',
                'category': EventRoleCategoryChoices.COORDINATOR,
            },

            # SUPPORT_STAFF
            {
                'code': 'FIRST_AID',
                'name': 'First Aider',
                'description': 'Qualified first aid responder on duty during the event.',
                'category': EventRoleCategoryChoices.SUPPORT_STAFF,
            },
            {
                'code': 'SAFEGUARD',
                'name': 'Safeguarding Officer',
                'description': 'Ensures safeguarding policies are upheld throughout the event.',
                'category': EventRoleCategoryChoices.SUPPORT_STAFF,
            },
            {
                'code': 'CATERING',
                'name': 'Catering Staff',
                'description': 'Prepares and serves food and beverages.',
                'category': EventRoleCategoryChoices.SUPPORT_STAFF,
            },
            {
                'code': 'SECURITY',
                'name': 'Security Staff',
                'description': 'Manages event security and access control.',
                'category': EventRoleCategoryChoices.SUPPORT_STAFF,
            },
        ]

        for data in roles:
            obj, created = EventRole.objects.get_or_create(
                code=data['code'],
                defaults={
                    'name': data['name'],
                    'description': data['description'],
                    'category': data['category'],
                },
            )
            self._log('EventRole', f"[{data['category']}] {data['name']}", created)

    # -----------------------------------------------------------------------
    # Dummy Users  (staging only)
    # -----------------------------------------------------------------------

    def _seed_event_types(self):
        from apps.events.models import EventType

        self.stdout.write('\nEvent Types:')

        event_types = [
            {
                'code': 'RETREAT',
                'name': 'Retreat',
                'description': 'A spiritual retreat event, often involving reflection and prayer.',
            },
            {
                'code': 'CONFERENCE',
                'name': 'Conference',
                'description': 'A formal gathering for discussion, learning, and networking.',
            },
            {
                'code': 'WORKSHOP',
                'name': 'Workshop',
                'description': 'An interactive session focused on skill-building or learning.',
            },
            {
                'code': 'SEMINAR',
                'name': 'Seminar',
                'description': 'An educational session or lecture on a specific topic.',
            },
            {
                'code': 'SOCIAL_EVENT',
                'name': 'Social Event',
                'description': "A casual gathering for socialising and community building.",
            },
            {
                'code': 'FUNDRAISER',
                'name': 'Fundraiser',
                'description': 'An event organised to raise funds for a cause or organisation.',
            },
            {
                'code': 'PFO',
                'name': 'Pastoral Formation Order',
                'description': 'An event focused on pastoral formation and development.',
            },
            {
                'code': 'HOUSEHOLD',
                'name': 'Household Event',
                'description': 'An event organised for a specific household or family group.',
            },
            {
                'code': 'FELLOWSHIP',
                'name': 'Fellowship Gathering',
                'description': 'A gathering for fellowship, community building, and shared activities.',
            }
        ]

        for data in event_types:
            obj, created = EventType.objects.get_or_create(
                code=data['code'],
                defaults={
                    'name': data['name'],
                    'description': data['description'],
                    'active': True,
                },
            )
            self._log('EventType', data['name'], created)

    def _seed_dummy_users(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()

        self.stdout.write('\nDummy Users:')

        DUMMY_PASSWORD = 'TESTPASSWORD12345@'

        users = [
            {
                'username': 'user1',
                'email': 'user1@test.local',
                'first_name': 'Test',
                'last_name': 'User One',
            },
            {
                'username': 'user2',
                'email': 'user2@test.local',
                'first_name': 'Test',
                'last_name': 'User Two',
            },
        ]

        for data in users:
            if User.objects.filter(username=data['username']).exists():
                self.stdout.write(
                    self.style.WARNING(f"  - Skipped (exists): {data['username']}")
                )
                continue

            User.objects.create_user(
                username=data['username'],
                email=data['email'],
                password=DUMMY_PASSWORD,
                first_name=data['first_name'],
                last_name=data['last_name'],
            )
            self.stdout.write(
                self.style.SUCCESS(f"  + Created user: {data['username']} / {DUMMY_PASSWORD}")
            )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _log(self, model_name: str, label: str, created: bool) -> None:
        if created:
            self.stdout.write(self.style.SUCCESS(f'  + {model_name}: {label}'))
        else:
            self.stdout.write(self.style.WARNING(f'  - {model_name} (exists): {label}'))
