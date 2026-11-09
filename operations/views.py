import csv
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Sum
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.access import properties_for_user, user_has_capability
from billing.models import Invoice

from .expenses import create_recurring_expense, record_expense, set_schedule_paused, update_expense, void_expense
from .forms import ExpenseCategoryForm, ExpenseForm, ExpenseImportForm, ExpenseVoidForm, InspectionCreateForm, InspectionPhotoForm, InspectionTemplateForm, MaintenanceAttachmentForm, MaintenanceTicketForm, MaintenanceTransitionForm, MaintenanceUpdateForm, RecurringExpenseForm, ReminderSettingsForm, UtilityCorrectionForm, UtilityMeterForm, UtilityReadingForm
from .inspections import add_inspection_photo, complete_inspection, create_inspection, update_inspection
from .models import Expense, ExpenseCategory, Inspection, InspectionItem, InspectionPhoto, InspectionTemplate, InspectionTemplateItem, MaintenanceAttachment, MaintenanceTicket, RecurringExpense, ReminderLog, ReminderSettings, UserNotification, UtilityMeter, UtilityReading
from .services import create_ticket, send_due_rent_reminders, send_manual_invoice_reminder, transition_ticket, update_ticket
from .utilities import bill_utility_readings, correct_utility_reading, record_utility_reading, update_utility_reading
from django.utils.translation import gettext_lazy as _


def _ticket_queryset(user, capability="maintenance-tickets.view"):
    if user_has_capability(user, capability):
        return MaintenanceTicket.objects.all()
    return MaintenanceTicket.objects.filter(property__in=properties_for_user(user, capability)).distinct()


def _require_ticket_access(user, capability="maintenance-tickets.view"):
    if not (user_has_capability(user, capability) or properties_for_user(user, capability).exists()):
        raise PermissionDenied


@login_required
def maintenance_list(request):
    _require_ticket_access(request.user)
    tickets = _ticket_queryset(request.user).select_related("property", "unit", "tenant", "assigned_to")
    status = request.GET.get("status", "")
    priority = request.GET.get("priority", "")
    query = request.GET.get("q", "").strip()
    if status:
        tickets = tickets.filter(status=status)
    if priority:
        tickets = tickets.filter(priority=priority)
    if query:
        tickets = tickets.filter(title__icontains=query)
    page = Paginator(tickets, 25).get_page(request.GET.get("page"))
    return render(request, "operations/maintenance_list.html", {"tickets": page, "status": status, "priority": priority, "query": query, "statuses": MaintenanceTicket.Status.choices, "priorities": MaintenanceTicket.Priority.choices, "can_create": user_has_capability(request.user, "maintenance-tickets.create") or properties_for_user(request.user, "maintenance-tickets.create").exists()})


@login_required
def maintenance_create(request):
    properties = properties_for_user(request.user, "maintenance-tickets.create")
    if not properties.exists() and not user_has_capability(request.user, "maintenance-tickets.create"):
        raise PermissionDenied
    form = MaintenanceTicketForm(request.POST or None, request.FILES or None, properties=properties)
    if request.method == "POST" and form.is_valid():
        values = form.cleaned_data.copy()
        attachment = values.pop("attachment", None)
        block_unit = values.pop("block_unit", False)
        ticket = create_ticket(actor=request.user, attachment=attachment, block_unit=block_unit, **values)
        messages.success(request, _("Ticket %(ticket)s created.") % {"ticket": ticket.reference})
        return redirect("maintenance_workspace", ticket_id=ticket.pk)
    return render(request, "properties/form.html", {"form": form, "title": "Report maintenance", "eyebrow": "Maintenance"})


@login_required
def maintenance_workspace(request, ticket_id):
    _require_ticket_access(request.user)
    ticket = get_object_or_404(_ticket_queryset(request.user).select_related("property", "unit", "tenant__user", "assigned_to", "created_by").prefetch_related("attachments", "history__actor"), pk=ticket_id)
    update_form = MaintenanceUpdateForm(instance=ticket)
    transition_form = MaintenanceTransitionForm(initial={"status": ticket.status})
    return render(request, "operations/maintenance_workspace.html", {"ticket": ticket, "update_form": update_form, "transition_form": transition_form, "attachment_form": MaintenanceAttachmentForm(), "can_update": user_has_capability(request.user, "maintenance-tickets.update") or properties_for_user(request.user, "maintenance-tickets.update").filter(pk=ticket.property_id).exists()})


@login_required
@require_POST
def maintenance_update(request, ticket_id):
    ticket = get_object_or_404(_ticket_queryset(request.user, "maintenance-tickets.update"), pk=ticket_id)
    form = MaintenanceUpdateForm(request.POST, instance=ticket)
    if form.is_valid():
        update_ticket(ticket, actor=request.user, **form.cleaned_data)
        messages.success(request, _("Maintenance ticket updated."))
    else:
        messages.error(request, _("The ticket could not be updated: ") + " ".join(sum(form.errors.values(), [])))
    return redirect("maintenance_workspace", ticket_id=ticket.pk)


@login_required
@require_POST
def maintenance_transition(request, ticket_id):
    ticket = get_object_or_404(_ticket_queryset(request.user, "maintenance-tickets.update"), pk=ticket_id)
    form = MaintenanceTransitionForm(request.POST)
    if form.is_valid():
        try:
            transition_ticket(ticket, form.cleaned_data["status"], actor=request.user, notes=form.cleaned_data["notes"])
            messages.success(request, _("Ticket status updated."))
        except ValidationError as error:
            messages.error(request, error.messages[0])
    return redirect("maintenance_workspace", ticket_id=ticket.pk)


@login_required
@require_POST
def maintenance_attachment_add(request, ticket_id):
    ticket = get_object_or_404(_ticket_queryset(request.user, "maintenance-tickets.update"), pk=ticket_id)
    form = MaintenanceAttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        upload = form.cleaned_data["file"]
        attachment = MaintenanceAttachment(ticket=ticket, file=upload, caption=form.cleaned_data["caption"], original_name=upload.name, mime_type=getattr(upload, "content_type", ""), size=upload.size)
        try:
            attachment.full_clean(); attachment.save(); messages.success(request, _("Attachment uploaded."))
        except ValidationError as error:
            messages.error(request, error.messages[0])
    else:
        messages.error(request, _("Choose a valid attachment."))
    return redirect("maintenance_workspace", ticket_id=ticket.pk)


@login_required
def maintenance_attachment_download(request, attachment_id):
    attachment = get_object_or_404(MaintenanceAttachment.objects.select_related("ticket"), pk=attachment_id)
    get_object_or_404(_ticket_queryset(request.user), pk=attachment.ticket_id)
    if not attachment.file.storage.exists(attachment.file.name):
        raise Http404
    return FileResponse(attachment.file.open("rb"), as_attachment=True, filename=attachment.original_name or attachment.file.name.rsplit("/", 1)[-1])


@login_required
def notifications(request):
    page = Paginator(UserNotification.objects.filter(recipient=request.user), 25).get_page(request.GET.get("page"))
    return render(request, "operations/notifications.html", {"notifications": page})


@login_required
@require_POST
def notification_read(request, notification_id):
    notification = get_object_or_404(UserNotification, pk=notification_id, recipient=request.user)
    notification.mark_read()
    return redirect(notification.url or "notifications")


@login_required
@require_POST
def notifications_read_all(request):
    UserNotification.objects.filter(recipient=request.user, read_at__isnull=True).update(read_at=timezone.now())
    messages.success(request, _("All notifications marked as read."))
    return redirect("notifications")


@login_required
def reminder_settings(request):
    if not user_has_capability(request.user, "roles.update"):
        raise PermissionDenied
    config = ReminderSettings.load()
    form = ReminderSettingsForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        form.save(); messages.success(request, _("Reminder settings saved.")); return redirect("reminder_settings")
    logs = ReminderLog.objects.all()[:20]
    return render(request, "operations/reminder_settings.html", {"form": form, "logs": logs})


@login_required
@require_POST
def run_reminders(request):
    if not user_has_capability(request.user, "reminders.send"):
        raise PermissionDenied
    count = send_due_rent_reminders()
    messages.success(request, _("Processed %(count)s reminder deliveries.") % {"count": count})
    return redirect("reminder_settings")


@login_required
@require_POST
def invoice_reminder(request, invoice_id):
    if not user_has_capability(request.user, "reminders.send"):
        raise PermissionDenied
    invoice = get_object_or_404(Invoice.objects.select_related("lease__tenant__user", "lease__primary_tenant__user"), pk=invoice_id)
    logs = send_manual_invoice_reminder(invoice)
    failures = sum(log.status == "failed" for log in logs)
    if logs and not failures:
        messages.success(request, _("Rent reminder sent."))
    elif logs:
        messages.warning(request, _("Reminder processed with %(count)s failed channels.") % {"count": failures})
    else:
        messages.info(request, _("This reminder was already sent today."))
    return redirect("invoice_workspace", invoice_id=invoice.pk)


def _expense_queryset(user, capability="expenses.view"):
    if user_has_capability(user, capability):
        return Expense.objects.all()
    return Expense.objects.filter(property__in=properties_for_user(user, capability)).distinct()


def _expense_properties(user, capability):
    return properties_for_user(user, capability)


@login_required
def expense_list(request):
    if not (user_has_capability(request.user, "expenses.view") or properties_for_user(request.user, "expenses.view").exists()):
        raise PermissionDenied
    expenses = _expense_queryset(request.user).select_related("property", "category", "voided_by")
    status = request.GET.get("status", Expense.Status.ACTIVE); property_id = request.GET.get("property"); currency = request.GET.get("currency", ""); date_from = request.GET.get("date_from", ""); date_to = request.GET.get("date_to", "")
    if status: expenses = expenses.filter(status=status)
    if property_id: expenses = expenses.filter(property_id=property_id)
    if currency: expenses = expenses.filter(currency=currency)
    if date_from: expenses = expenses.filter(incurred_on__gte=date_from)
    if date_to: expenses = expenses.filter(incurred_on__lte=date_to)
    summary = list(expenses.values("currency").annotate(total=Sum("amount")).order_by("currency"))
    return render(request, "operations/expense_list.html", {"expenses": Paginator(expenses, 25).get_page(request.GET.get("page")), "summary": summary, "status": status, "property_id": property_id, "currency": currency, "date_from": date_from, "date_to": date_to, "properties": _expense_properties(request.user, "expenses.view").order_by("name"), "currencies": Expense.objects.order_by("currency").values_list("currency", flat=True).distinct(), "statuses": Expense.Status.choices, "can_create": user_has_capability(request.user, "expenses.create") or properties_for_user(request.user, "expenses.create").exists(), "can_update": user_has_capability(request.user, "expenses.update"), "can_void": user_has_capability(request.user, "expenses.delete")})


@login_required
def expense_create(request):
    properties = _expense_properties(request.user, "expenses.create")
    if not properties.exists() and not user_has_capability(request.user, "expenses.create"): raise PermissionDenied
    form = ExpenseForm(request.POST or None, request.FILES or None, properties=properties)
    if request.method == "POST" and form.is_valid():
        values = form.cleaned_data.copy(); receipt = values.pop("receipt", None)
        expense = record_expense(actor=request.user, receipt=receipt, **values); messages.success(request, _("Expense recorded.")); return redirect("expense_list")
    return render(request, "properties/form.html", {"form": form, "title": "Record expense", "eyebrow": "Expenses"})


@login_required
def expense_edit(request, expense_id):
    expense = get_object_or_404(_expense_queryset(request.user, "expenses.update"), pk=expense_id)
    form = ExpenseForm(request.POST or None, request.FILES or None, instance=expense, properties=_expense_properties(request.user, "expenses.update"))
    if request.method == "POST" and form.is_valid():
        values = form.cleaned_data.copy(); receipt = values.pop("receipt", None)
        try: update_expense(expense, receipt=receipt, **values); messages.success(request, _("Expense updated.")); return redirect("expense_list")
        except ValidationError as error: form.add_error(None, error.messages[0])
    return render(request, "properties/form.html", {"form": form, "title": "Edit expense", "eyebrow": "Expenses"})


@login_required
@require_POST
def expense_void(request, expense_id):
    expense = get_object_or_404(_expense_queryset(request.user, "expenses.delete"), pk=expense_id)
    form = ExpenseVoidForm(request.POST)
    if form.is_valid():
        try: void_expense(expense, actor=request.user, reason=form.cleaned_data["reason"]); messages.success(request, _("Expense voided."))
        except ValidationError as error: messages.error(request, error.messages[0])
    return redirect("expense_list")


@login_required
def expense_receipt(request, expense_id):
    expense = get_object_or_404(_expense_queryset(request.user), pk=expense_id)
    if not expense.receipt or not expense.receipt.storage.exists(expense.receipt.name): raise Http404
    return FileResponse(expense.receipt.open("rb"), as_attachment=True, filename=expense.receipt_original_name or expense.receipt.name.rsplit("/", 1)[-1])


@login_required
def expense_export(request):
    if not user_has_capability(request.user, "expenses.export"): raise PermissionDenied
    response = HttpResponse(content_type="text/csv"); response["Content-Disposition"] = 'attachment; filename="expenses.csv"'
    writer = csv.writer(response); writer.writerow(("property", "category", "amount", "currency", "incurred_on", "vendor", "reference", "description", "notes", "status"))
    for expense in _expense_queryset(request.user).select_related("property", "category"):
        writer.writerow((expense.property.name, expense.category.name, expense.amount, expense.currency, expense.incurred_on, expense.vendor, expense.reference, expense.description, expense.notes, expense.status))
    return response


@login_required
def expense_import(request):
    if not user_has_capability(request.user, "expenses.import"): raise PermissionDenied
    form = ExpenseImportForm(request.POST or None, request.FILES or None); preview = []; errors = []
    if request.method == "POST" and form.is_valid():
        try: rows = list(csv.DictReader(io.StringIO(form.cleaned_data["file"].read().decode("utf-8-sig"))))
        except (UnicodeDecodeError, csv.Error): rows = []; errors.append("The CSV file could not be read.")
        accessible = {item.name: item for item in _expense_properties(request.user, "expenses.import")}; categories = {item.name: item for item in ExpenseCategory.objects.all()}
        clean = []
        for number, row in enumerate(rows, start=2):
            if row.get("property") not in accessible or row.get("category") not in categories:
                errors.append(f"Row {number}: unknown or inaccessible property/category."); continue
            try:
                item = {"property": row["property"], "category": row["category"], "amount": str(row["amount"]), "currency": (row.get("currency") or "OMR").upper(), "incurred_on": row["incurred_on"], "vendor": row.get("vendor", ""), "reference": row.get("reference", ""), "description": row.get("description", ""), "notes": row.get("notes", "")}
                candidate = Expense(property=accessible[item["property"]], category=categories[item["category"]], amount=item["amount"], currency=item["currency"], incurred_on=item["incurred_on"], description=item["description"], created_by=request.user); candidate.full_clean(exclude=("incurred_on",)); clean.append(item); preview.append(item)
            except (ValidationError, KeyError) as error: errors.append(f"Row {number}: {error}")
        request.session["expense_import_rows"] = clean
    return render(request, "operations/expense_import.html", {"form": form, "preview": preview, "errors": errors})


@login_required
@require_POST
def expense_import_confirm(request):
    if not user_has_capability(request.user, "expenses.import"): raise PermissionDenied
    rows = request.session.pop("expense_import_rows", []); properties = {item.name: item for item in _expense_properties(request.user, "expenses.import")}; categories = {item.name: item for item in ExpenseCategory.objects.all()}; count = 0
    for row in rows:
        record_expense(actor=request.user, property=properties[row.pop("property")], category=categories[row.pop("category")], **row); count += 1
    messages.success(request, _("Imported %(count)s expenses.") % {"count": count}); return redirect("expense_list")


@login_required
def recurring_expense_list(request):
    if not (user_has_capability(request.user, "expenses.view") or properties_for_user(request.user, "expenses.view").exists()): raise PermissionDenied
    schedules = RecurringExpense.objects.filter(property__in=_expense_properties(request.user, "expenses.view")).select_related("property", "category")
    return render(request, "operations/recurring_list.html", {"schedules": Paginator(schedules, 25).get_page(request.GET.get("page")), "can_create": user_has_capability(request.user, "expenses.create"), "can_update": user_has_capability(request.user, "expenses.update")})


@login_required
def recurring_expense_create(request):
    properties = _expense_properties(request.user, "expenses.create")
    if not properties.exists() and not user_has_capability(request.user, "expenses.create"): raise PermissionDenied
    form = RecurringExpenseForm(request.POST or None, properties=properties)
    if request.method == "POST" and form.is_valid():
        create_recurring_expense(actor=request.user, **form.cleaned_data); messages.success(request, _("Recurring expense added.")); return redirect("recurring_expense_list")
    return render(request, "properties/form.html", {"form": form, "title": "Add recurring expense", "eyebrow": "Expenses"})


@login_required
@require_POST
def recurring_expense_pause(request, schedule_id):
    schedule = get_object_or_404(RecurringExpense, pk=schedule_id, property__in=_expense_properties(request.user, "expenses.update"))
    try: set_schedule_paused(schedule, request.POST.get("action") != "resume"); messages.success(request, _("Recurring expense updated."))
    except ValidationError as error: messages.error(request, error.messages[0])
    return redirect("recurring_expense_list")


@login_required
def expense_categories(request):
    if not user_has_capability(request.user, "roles.update"): raise PermissionDenied
    form = ExpenseCategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, _("Expense category saved.")); return redirect("expense_categories")
    return render(request, "operations/expense_categories.html", {"form": form, "categories": ExpenseCategory.objects.all()})


@login_required
def utility_list(request):
    properties = properties_for_user(request.user, "units.view")
    if not properties.exists() and not user_has_capability(request.user, "units.view"): raise PermissionDenied
    meters = UtilityMeter.objects.filter(unit__property__in=properties).select_related("unit__property").prefetch_related("readings")
    return render(request, "operations/utility_list.html", {"meters": meters, "can_update": user_has_capability(request.user, "units.update") or properties_for_user(request.user, "units.update").exists()})


@login_required
def utility_meter_create(request):
    properties = properties_for_user(request.user, "units.update")
    if not properties.exists() and not user_has_capability(request.user, "units.update"): raise PermissionDenied
    form = UtilityMeterForm(request.POST or None, properties=properties)
    if request.method == "POST" and form.is_valid(): meter = form.save(commit=False); meter.full_clean(); meter.save(); messages.success(request, _("Utility meter added.")); return redirect("utility_meter", meter_id=meter.pk)
    return render(request, "properties/form.html", {"form": form, "title": "Add utility meter", "eyebrow": "Utilities"})


@login_required
def utility_meter(request, meter_id):
    properties = properties_for_user(request.user, "units.view")
    meter = get_object_or_404(UtilityMeter.objects.select_related("unit__property"), pk=meter_id, unit__property__in=properties)
    return render(request, "operations/utility_meter.html", {"meter": meter, "readings": meter.readings.select_related("invoice_line_item__invoice", "corrects_reading"), "reading_form": UtilityReadingForm(initial={"reading_date": timezone.localdate()}), "correction_form": UtilityCorrectionForm(), "can_update": user_has_capability(request.user, "units.update") or properties_for_user(request.user, "units.update").filter(pk=meter.unit.property_id).exists()})


@login_required
@require_POST
def utility_reading_add(request, meter_id):
    meter = get_object_or_404(UtilityMeter, pk=meter_id, unit__property__in=properties_for_user(request.user, "units.update")); form = UtilityReadingForm(request.POST)
    if form.is_valid():
        try: record_utility_reading(meter=meter, actor=request.user, **form.cleaned_data); messages.success(request, _("Meter reading recorded."))
        except ValidationError as error: messages.error(request, error.messages[0])
    else: messages.error(request, _("Reading could not be recorded."))
    return redirect("utility_meter", meter_id=meter.pk)


@login_required
@require_POST
def utility_reading_edit(request, reading_id):
    reading = get_object_or_404(UtilityReading.objects.select_related("meter__unit__property"), pk=reading_id, meter__unit__property__in=properties_for_user(request.user, "units.update")); form = UtilityReadingForm(request.POST)
    if form.is_valid():
        try: update_utility_reading(reading, current_reading=form.cleaned_data["current_reading"], notes=form.cleaned_data["notes"]); messages.success(request, _("Reading updated."))
        except ValidationError as error: messages.error(request, error.messages[0])
    return redirect("utility_meter", meter_id=reading.meter_id)


@login_required
@require_POST
def utility_reading_correct(request, reading_id):
    reading = get_object_or_404(UtilityReading.objects.select_related("meter__unit__property"), pk=reading_id, meter__unit__property__in=properties_for_user(request.user, "units.update")); form = UtilityCorrectionForm(request.POST)
    if form.is_valid():
        try: correct_utility_reading(reading, actor=request.user, **form.cleaned_data); messages.success(request, _("Correction recorded."))
        except ValidationError as error: messages.error(request, error.messages[0])
    return redirect("utility_meter", meter_id=reading.meter_id)


@login_required
@require_POST
def utility_reading_bill(request, reading_id):
    reading = get_object_or_404(UtilityReading.objects.select_related("meter__unit__property"), pk=reading_id, meter__unit__property__in=properties_for_user(request.user, "units.update"))
    try: bill_utility_readings([reading], actor=request.user); messages.success(request, _("Utility charge added to the open invoice."))
    except ValidationError as error: messages.error(request, error.messages[0])
    return redirect("utility_meter", meter_id=reading.meter_id)


def _inspection_queryset(user, capability="inspections.view"):
    return Inspection.objects.filter(property__in=properties_for_user(user, capability)).distinct()


@login_required
def inspection_list(request):
    inspections = _inspection_queryset(request.user).select_related("property", "unit", "lease", "template", "inspector")
    if not inspections.exists() and not (user_has_capability(request.user, "inspections.view") or properties_for_user(request.user, "inspections.view").exists()): raise PermissionDenied
    for field in ("status", "inspection_type", "property"):
        if request.GET.get(field): inspections = inspections.filter(**{f"{field}_id" if field == "property" else field: request.GET[field]})
    return render(request, "operations/inspection_list.html", {"inspections": Paginator(inspections, 25).get_page(request.GET.get("page")), "statuses": Inspection.Status.choices, "types": InspectionTemplate.Type.choices, "properties": properties_for_user(request.user, "inspections.view"), "can_create": user_has_capability(request.user, "inspections.create") or properties_for_user(request.user, "inspections.create").exists()})


@login_required
def inspection_create(request):
    properties = properties_for_user(request.user, "inspections.create")
    if not properties.exists() and not user_has_capability(request.user, "inspections.create"): raise PermissionDenied
    form = InspectionCreateForm(request.POST or None, properties=properties)
    if request.method == "POST" and form.is_valid():
        try:
            values = form.cleaned_data; inspection = create_inspection(template=values["template"], property_obj=values["property"], unit=values["unit"], lease=values["lease"], inspection_date=values["inspection_date"], inspector=request.user, notes=values["notes"]); messages.success(request, _("Inspection created.")); return redirect("inspection_workspace", inspection_id=inspection.pk)
        except ValidationError as error: form.add_error(None, error.messages[0])
    return render(request, "properties/form.html", {"form": form, "title": "Create inspection", "eyebrow": "Inspections"})


@login_required
def inspection_workspace(request, inspection_id):
    inspection = get_object_or_404(_inspection_queryset(request.user).select_related("property", "unit", "lease", "template", "inspector", "completed_by").prefetch_related("items__photos"), pk=inspection_id)
    return render(request, "operations/inspection_workspace.html", {"inspection": inspection, "photo_form": InspectionPhotoForm(), "conditions": InspectionItem.Condition.choices, "can_update": (user_has_capability(request.user, "inspections.update") or properties_for_user(request.user, "inspections.update").filter(pk=inspection.property_id).exists()) and inspection.status != Inspection.Status.COMPLETED, "can_complete": user_has_capability(request.user, "inspections.complete") or properties_for_user(request.user, "inspections.complete").filter(pk=inspection.property_id).exists()})


@login_required
@require_POST
def inspection_update(request, inspection_id):
    inspection = get_object_or_404(_inspection_queryset(request.user, "inspections.update"), pk=inspection_id); rows = [{"id": item.pk, "condition": request.POST.get(f"condition_{item.pk}", ""), "notes": request.POST.get(f"notes_{item.pk}", "")} for item in inspection.items.all()]
    try: update_inspection(inspection, actor=request.user, notes=request.POST.get("notes", ""), damage_observations=request.POST.get("damage_observations", ""), items=rows); messages.success(request, _("Inspection draft saved."))
    except ValidationError as error: messages.error(request, error.messages[0])
    return redirect("inspection_workspace", inspection_id=inspection.pk)


@login_required
@require_POST
def inspection_complete(request, inspection_id):
    inspection = get_object_or_404(_inspection_queryset(request.user, "inspections.complete"), pk=inspection_id)
    try: complete_inspection(inspection, actor=request.user); messages.success(request, _("Inspection completed and locked."))
    except ValidationError as error: messages.error(request, error.messages[0])
    return redirect("inspection_workspace", inspection_id=inspection.pk)


@login_required
@require_POST
def inspection_photo_add(request, item_id):
    item = get_object_or_404(InspectionItem.objects.select_related("inspection__property"), pk=item_id, inspection__property__in=properties_for_user(request.user, "inspections.update")); form = InspectionPhotoForm(request.POST, request.FILES)
    if form.is_valid():
        try: add_inspection_photo(item, form.cleaned_data["file"], form.cleaned_data["caption"]); messages.success(request, _("Inspection photo uploaded."))
        except ValidationError as error: messages.error(request, error.messages[0])
    return redirect("inspection_workspace", inspection_id=item.inspection_id)


@login_required
def inspection_photo_download(request, photo_id):
    photo = get_object_or_404(InspectionPhoto.objects.select_related("item__inspection__property"), pk=photo_id, item__inspection__property__in=properties_for_user(request.user, "inspections.view"))
    if not photo.file.storage.exists(photo.file.name): raise Http404
    return FileResponse(photo.file.open("rb"), content_type=photo.mime_type or "application/octet-stream", filename=photo.original_name or photo.file.name.rsplit("/", 1)[-1])


@login_required
def inspection_templates(request):
    if not user_has_capability(request.user, "inspection-templates.manage"): raise PermissionDenied
    form = InspectionTemplateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        template = form.save(); template.items.all().delete(); InspectionTemplateItem.objects.bulk_create([InspectionTemplateItem(template=template, label=line.strip(), sort_order=index) for index, line in enumerate(form.cleaned_data["checklist"].splitlines()) if line.strip()]); messages.success(request, _("Inspection template saved.")); return redirect("inspection_templates")
    return render(request, "operations/inspection_templates.html", {"form": form, "templates": InspectionTemplate.objects.prefetch_related("items")})
