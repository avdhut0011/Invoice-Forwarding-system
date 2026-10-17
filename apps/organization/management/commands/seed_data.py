from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta, date
from decimal import Decimal
from apps.organization.models import LegalEntity, Unit, User, RoleChoices, UnitAccess
from apps.procurement.models import PaymentTerms, Supplier, PurchaseOrder, OrderLine
from apps.receipts.models import GoodsReceipt, ReceiptLine, DocTypeChoices, PaymentCategoryChoices, ReceiptStatusChoices
from apps.invoices.models import Invoice, InvoiceAllocation, InvoiceTypeChoices, InvoiceStatusChoices
from apps.workflow.models import HandoverBatch, HandoverItem, HandoverTypeChoices, WorkflowTask, TaskTypeChoices, TaskStatusChoices

class Command(BaseCommand):
    help = 'Seeds master data and sample workflow records for Ashoka FMS'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding master data..."))

        # 1. Legal Entity
        legal_entity, _ = LegalEntity.objects.get_or_create(
            code="AEF",
            defaults={"name": "Ashoka Education Foundation", "gstin": "27AAATA1234A1Z5"}
        )

        # 2. Educational Units
        unit_names = [
            "Ashoka Universal School - Ashoka Marg",
            "Ashoka Universal School - Arjun Nagar",
            "Ashoka Universal School - Sinnar",
            "Ashoka Universal School (PP) - Ashoka Marg",
            "Ashoka Universal School (PP) - Arjun Nagar",
            "Ashoka Global Academy - Arjun Nagar",
            "Ashoka Junior College (ISC) - Ashoka Marg",
            "Ashoka Business School - Rane Nagar",
            "Ashoka Education Foundation - Ashoka Marg",
            "Ashoka College of Education - Ashoka Marg",
            "Ashoka International Centre for Educational Studies & Research - Ashoka Marg",
            "Ashoka Centre for Business & Computer Studies - Chandsi",
            "Ashoka Universal School - Wadala",
        ]

        units = {}
        for name in unit_names:
            u, _ = Unit.objects.get_or_create(
                name=name,
                defaults={"legal_entity": legal_entity, "code": name[:10].upper().replace(" ", "")}
            )
            units[name] = u

        primary_unit = units["Ashoka Universal School - Ashoka Marg"]

        # 3. Payment Terms
        terms_data = [
            ("Immediate / Cash", 0),
            ("Net 30 Days", 30),
            ("Net 45 Days", 45),
            ("Net 60 Days", 60),
        ]
        payment_terms = {}
        for name, days in terms_data:
            pt, _ = PaymentTerms.objects.get_or_create(name=name, defaults={"credit_days": days})
            payment_terms[name] = pt

        # 4. Suppliers
        suppliers_data = [
            ("Ashoka Stationers & Printers", "SUP-001", "sales@ashokastationers.com", "9822011111", "27AAACS1111A1Z1", payment_terms["Net 30 Days"]),
            ("Shree Logistics & Transport", "SUP-002", "info@shreelogistics.com", "9822022222", "27AAACS2222A1Z2", payment_terms["Immediate / Cash"]),
            ("Apex Infotech Solutions", "SUP-003", "contact@apexinfotech.com", "9822033333", "27AAACS3333A1Z3", payment_terms["Net 45 Days"]),
            ("Metro Paper Mills Ltd", "SUP-004", "order@metropaper.com", "9822044444", "27AAACS4444A1Z4", payment_terms["Net 30 Days"]),
            ("Global Office Supplies", "SUP-005", "care@globalofficesup.com", "9822055555", "27AAACS5555A1Z5", payment_terms["Net 60 Days"]),
        ]
        suppliers = {}
        for name, code, email, phone, gstin, pt in suppliers_data:
            s, _ = Supplier.objects.get_or_create(
                name=name,
                defaults={"code": code, "email": email, "phone": phone, "gstin": gstin, "payment_terms": pt}
            )
            suppliers[name] = s

        # 5. Users
        users_config = [
            # Store staff
            ("chandrashekhar", "Chandrashekhar", "Aher", "chandrashekhar.aher@ausindia.org", RoleChoices.STORE),
            ("nikita", "Nikita", "Shelke", "nikita.shelke@ausindia.org", RoleChoices.STORE),
            ("mukesh", "Mukesh", "Jadhav", "mukesh.jadhav@ausindia.org", RoleChoices.STORE),
            ("shrikant", "Shrikant", "Zadbuke", "shrikant.zadbuke@ashokaglobalacademy.com", RoleChoices.STORE),
            ("kavita", "Kavita", "Jadhav", "kavita.jadhav@ausindia.org", RoleChoices.STORE),
            ("rohan", "Rohan", "Brahmankar", "rohan.bramhankar@ausindia.org", RoleChoices.STORE),
            # Purchase staff
            ("vishal", "Vishal", "Khairnar", "vishal.khairnar@aef.edu.in", RoleChoices.PURCHASE),
            ("vilas", "Vilas", "Dhumal", "vilas.dhumal@aef.edu.in", RoleChoices.PURCHASE),
            ("ashwin", "Ashwin", "Khairnar", "ashwin.khairnar@aef.edu.in", RoleChoices.PURCHASE),
            ("vishwanath", "Vishwanath", "Srivastav", "vishwanath.srivastav@aef.edu.in", RoleChoices.PURCHASE),
            ("sagar", "Sagar", "Tak", "sagar.tak@aef.edu.in", RoleChoices.PURCHASE),
            ("dipali", "Dipali", "Nikumbh", "dipali.nikumbh@aef.edu.in", RoleChoices.PURCHASE),
            ("prashant", "Prashant", "Joshi", "prashant.joshi@ausindia.org", RoleChoices.PURCHASE),
            ("alankar", "Alankar", "Wadgaonkar", "alankar.wadgaonkar@ausindia.org", RoleChoices.PURCHASE),
            # Accounts
            ("accounts", "Accounts", "Department", "accounts@aef.edu.in", RoleChoices.ACCOUNTS),
            # Manager
            ("manager", "Finance", "Manager", "manager@aef.edu.in", RoleChoices.MANAGER),
            # Admin
            ("admin", "System", "Administrator", "admin@aef.edu.in", RoleChoices.ADMIN),
        ]

        users = {}
        for username, fname, lname, email, role in users_config:
            u = User.objects.filter(username=username).first()
            if not u:
                u = User.objects.create_user(
                    username=username,
                    email=email,
                    first_name=fname,
                    last_name=lname,
                    role=role,
                    primary_unit=primary_unit,
                    is_staff=(role in [RoleChoices.ADMIN, RoleChoices.MANAGER]),
                    is_superuser=(role == RoleChoices.ADMIN)
                )
                u.set_password("password123")
                u.save()
            users[username] = u
            UnitAccess.objects.get_or_create(user=u, unit=primary_unit, defaults={"can_create": True, "can_approve": True})

        # 6. Sample Data: Purchase Orders
        po1, _ = PurchaseOrder.objects.get_or_create(
            unit=primary_unit,
            po_number="PO/2026/00142",
            defaults={
                "supplier": suppliers["Ashoka Stationers & Printers"],
                "order_date": date.today() - timedelta(days=15),
                "total_amount": Decimal("100000.00"),
                "created_by": users["vishal"]
            }
        )
        OrderLine.objects.get_or_create(
            purchase_order=po1,
            line_number=1,
            defaults={
                "description": "A4 Copier Paper Reams (500 sheets)",
                "quantity": Decimal("250.000"),
                "unit_price": Decimal("240.00"),
                "line_total": Decimal("60000.00"),
            }
        )
        OrderLine.objects.get_or_create(
            purchase_order=po1,
            line_number=2,
            defaults={
                "description": "Student Progress Registers & Examination Booklets",
                "quantity": Decimal("400.000"),
                "unit_price": Decimal("100.00"),
                "line_total": Decimal("40000.00"),
            }
        )

        # 7. Sample Goods Receipts
        gr1, _ = GoodsReceipt.objects.get_or_create(
            st_number="ST-00001",
            defaults={
                "unit": primary_unit,
                "supplier": suppliers["Ashoka Stationers & Printers"],
                "supplier_name_raw": "Ashoka Stationers & Printers",
                "material_date": date.today() - timedelta(days=10),
                "doc_type": DocTypeChoices.PO,
                "po_wo_number": "PO/2026/00142",
                "dc_number": "DC-9921",
                "grn_number": "GRN-2026-081",
                "grn_date": date.today() - timedelta(days=10),
                "description": "A4 Copier Paper Reams (250 reams delivered in good condition)",
                "payment_category": PaymentCategoryChoices.CREDIT,
                "is_invoice_received": True,
                "assigned_purchase_person": users["vishal"],
                "submitted_by": users["chandrashekhar"],
                "store_person_raw": "Chandrashekhar Aher",
                "submitter_email": "chandrashekhar.aher@ausindia.org",
                "status": ReceiptStatusChoices.BILL_LINKED,
                "bill_unique_id": "BILL-00001",
            }
        )
        ReceiptLine.objects.get_or_create(
            goods_receipt=gr1,
            item_description="A4 Copier Paper Reams (500 sheets)",
            defaults={
                "received_quantity": Decimal("250.000"),
                "accepted_quantity": Decimal("250.000"),
                "invoiced_quantity": Decimal("250.000"),
                "unit_price": Decimal("240.00")
            }
        )

        gr2, _ = GoodsReceipt.objects.get_or_create(
            st_number="ST-00002",
            defaults={
                "unit": primary_unit,
                "supplier": suppliers["Ashoka Stationers & Printers"],
                "supplier_name_raw": "Ashoka Stationers & Printers",
                "material_date": date.today() - timedelta(days=9),
                "doc_type": DocTypeChoices.PO,
                "po_wo_number": "PO/2026/00142",
                "dc_number": "DC-9934",
                "grn_number": "GRN-2026-082",
                "grn_date": date.today() - timedelta(days=9),
                "description": "Examination Booklets (400 booklets for term assessments)",
                "payment_category": PaymentCategoryChoices.CREDIT,
                "is_invoice_received": True,
                "assigned_purchase_person": users["vishal"],
                "submitted_by": users["chandrashekhar"],
                "store_person_raw": "Chandrashekhar Aher",
                "submitter_email": "chandrashekhar.aher@ausindia.org",
                "status": ReceiptStatusChoices.BILL_LINKED,
                "bill_unique_id": "BILL-00001",
            }
        )
        ReceiptLine.objects.get_or_create(
            goods_receipt=gr2,
            item_description="Student Progress Registers & Examination Booklets",
            defaults={
                "received_quantity": Decimal("400.000"),
                "accepted_quantity": Decimal("400.000"),
                "invoiced_quantity": Decimal("400.000"),
                "unit_price": Decimal("100.00")
            }
        )

        gr3, _ = GoodsReceipt.objects.get_or_create(
            st_number="ST-00003",
            defaults={
                "unit": primary_unit,
                "supplier": suppliers["Apex Infotech Solutions"],
                "supplier_name_raw": "Apex Infotech Solutions",
                "material_date": date.today() - timedelta(days=2),
                "doc_type": DocTypeChoices.PO,
                "po_wo_number": "PO/2026/00188",
                "dc_number": "DC-1004",
                "grn_number": "GRN-2026-095",
                "grn_date": date.today() - timedelta(days=2),
                "description": "Classroom Projector Lamps & HDMI Extenders",
                "payment_category": PaymentCategoryChoices.CREDIT,
                "is_invoice_received": True,
                "assigned_purchase_person": users["vishal"],
                "submitted_by": users["nikita"],
                "store_person_raw": "Nikita Shelke",
                "submitter_email": "nikita.shelke@ausindia.org",
                "status": ReceiptStatusChoices.CUSTODY_ACKNOWLEDGED,
            }
        )
        ReceiptLine.objects.get_or_create(
            goods_receipt=gr3,
            item_description="Classroom Projector Lamps",
            defaults={
                "received_quantity": Decimal("10.000"),
                "accepted_quantity": Decimal("10.000"),
                "invoiced_quantity": Decimal("0.000"),
                "unit_price": Decimal("2500.00")
            }
        )

        # 8. Sample Invoice: 1 invoice allocating across 2 receipts (matches blueprint INR 100,000 example!)
        inv1, _ = Invoice.objects.get_or_create(
            bill_unique_id="BILL-00001",
            defaults={
                "unit": primary_unit,
                "supplier": suppliers["Ashoka Stationers & Printers"],
                "supplier_name_raw": "Ashoka Stationers & Printers",
                "supplier_code": "SUP-001",
                "invoice_number": "INV-2026-781",
                "invoice_date": date.today() - timedelta(days=8),
                "gross_amount": Decimal("100000.00"),
                "tax_amount": Decimal("0.00"),
                "net_amount": Decimal("100000.00"),
                "due_date": date.today() + timedelta(days=22),
                "payment_category": "Credit",
                "grn_received_from_stores_on": date.today() - timedelta(days=8),
                "purchase_remark": "Verified with PO/2026/00142. Full quantity received against GRN 081 & 082.",
                "status": InvoiceStatusChoices.SUBMITTED_TO_ACCOUNTS,
                "submitted_by": users["vishal"],
                "purchase_person_raw": "Vishal Khairnar",
                "submitter_email": "vishal.khairnar@aef.edu.in",
            }
        )

        # Line-level allocations
        InvoiceAllocation.objects.get_or_create(
            invoice=inv1,
            goods_receipt=gr1,
            defaults={"allocated_amount": Decimal("60000.00"), "allocated_quantity": Decimal("250.000"), "notes": "GRN-2026-081 allocation"}
        )
        InvoiceAllocation.objects.get_or_create(
            invoice=inv1,
            goods_receipt=gr2,
            defaults={"allocated_amount": Decimal("40000.00"), "allocated_quantity": Decimal("400.000"), "notes": "GRN-2026-082 allocation"}
        )

        # Handover batch to Accounts
        hb, _ = HandoverBatch.objects.get_or_create(
            batch_number="HB-00001",
            defaults={
                "handover_type": HandoverTypeChoices.PURCHASE_TO_ACCOUNTS,
                "unit": primary_unit,
                "sender": users["vishal"],
                "sender_name_raw": "Vishal Khairnar",
                "intended_recipient": users["accounts"],
                "intended_recipient_name_raw": "Accounts Department",
                "checklist_summary": "1 Bill (BILL-00001), 2 GRNs attached (081, 082)",
                "is_acknowledged": False
            }
        )
        HandoverItem.objects.get_or_create(batch=hb, invoice=inv1, defaults={"is_received": True})

        # Workflow Task for Accounts
        WorkflowTask.objects.get_or_create(
            handover_batch=hb,
            task_type=TaskTypeChoices.CUSTODY_ACK,
            defaults={
                "title": f"Acknowledge Custody of Batch {hb.batch_number}",
                "description": "Verify physical receipt of invoice BILL-00001 from Purchase (Vishal Khairnar)",
                "assigned_to": users["accounts"],
                "unit": primary_unit,
                "invoice": inv1,
                "deadline": timezone.now() + timedelta(hours=4),
                "status": TaskStatusChoices.OPEN
            }
        )

        self.stdout.write(self.style.SUCCESS("Master data and sample workflow records successfully seeded!"))
