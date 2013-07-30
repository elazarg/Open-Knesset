# encoding: utf-8
import datetime
from django.db.models.signals import post_save, pre_delete, post_delete
from django.contrib.contenttypes.models import ContentType
from planet.models import Feed, Post
from actstream import action
from actstream.models import Follow
from knesset.utils import disable_for_loaddata
from agendas.models import AgendaVote, AgendaMeeting, AgendaBill, Agenda

def _connect_all():
    def _do_send(instance, **kwargs):
        kwargs['timestamp'] = datetime.datetime.now()
        action.send(instance.agenda, **kwargs)
        
    fmt_created = u'agenda {atype} ascribed', u'agenda "{name}" ascribed to {atype} "{title}"'
    fmt_updated = u'agenda {atype} relation updated', u'relation between agenda "{name}" and {atype} "{title}" was updated'
    fmt_removed = u'agenda {atype} removed', u'agenda "{name}" removed from {atype} "{title}"'
    
    agenda_types = (
         ('vote', lambda x : x.vote.title, AgendaVote),
         ('meeting', lambda x : x.meeting.title(), AgendaMeeting),
         ('bill', lambda x : x.bill.full_title, AgendaBill),
    )
    
    for atype, titlegetter, aclass in agenda_types:
        @disable_for_loaddata
        def record_ascription_action(sender, created, instance, **kwargs):
            if created:  verb, fmt = fmt_created
            else:        verb, fmt = fmt_updated
            description = fmt.format(name=instance.agenda.name, title=titlegetter(instance), atype=atype)
            _do_send(instance, verb=verb.format(atype), target=instance, description=description)
        
        post_save.connect(record_ascription_action, sender=aclass)
    
        @disable_for_loaddata
        def record_removal_action(sender, instance, **kwargs):
            verb, fmt = fmt_removed
            description = fmt.format(name=instance.agenda.name, title=titlegetter(instance), atype=atype)
            _do_send(instance, verb=verb, target=getattr(instance, atype), description=description)
        
        pre_delete.connect(record_removal_action, sender=aclass)
        
    @disable_for_loaddata
    def update_num_followers(sender, instance, **kwargs):
        agenda = instance.actor
        if isinstance(agenda, Agenda):
            agenda.num_followers = Follow.objects.filter(
                content_type=ContentType.objects.get(
                        app_label="agendas",
                        model="agenda").id,
                object_id=agenda.id).count()
            agenda.save()

    post_delete.connect(update_num_followers, sender=Follow)
    post_save.connect(update_num_followers, sender=Follow)
            
_connect_all()
'''
@disable_for_loaddata
def record_agenda_meeting_ascription_action(sender, created, instance, **kwargs):
    if created:
        verb, fmt = 'agenda meeting ascribed', u'agenda "{}" ascribed to meeting "{}"'
    else:
        verb, fmt = 'agenda meeting relation_updated', u'relation between agenda "{}" and meeting "{}" was updated'
    description = fmt.format(instance.agenda.name, instance.meeting.title())
    _do_send(instance, verb=verb, target=instance, description=description)
    
post_save.connect(record_agenda_meeting_ascription_action, sender=AgendaMeeting)

@disable_for_loaddata
def record_agenda_meeting_removal_action(sender, instance, **kwargs):
    verb, fmt = 'agenda meeting removed', u'agenda "{}" removed from meeting "{}"'
    description = fmt.format(instance.agenda.name, instance.meeting.title())
    _do_send(instance, verb=verb, target=instance.meeting, description=description)
    
pre_delete.connect(record_agenda_meeting_removal_action, sender=AgendaMeeting)

@disable_for_loaddata
def record_agenda_bill_ascription_action(sender, created, instance, **kwargs):
    if created:
        verb, fmt = 'agenda bill ascribed', u'agenda "{}" ascribed to bill "{}"'
    else:
        verb, fmt = 'agenda bill relation updated', u'relation between agenda "{}" and bill "{}" was updated'
    description=fmt.format(instance.agenda.name, instance.bill.full_title)
    _do_send(instance, verb=verb, target=instance, description=description)
    
post_save.connect(record_agenda_bill_ascription_action, sender=AgendaBill)

@disable_for_loaddata
def record_agenda_bill_removal_action(sender, instance, **kwargs):
    verb, fmt = 'agenda bill removed', u'agenda {} removed from bill {}'
    description=fmt.format(instance.agenda.name, instance.bill.full_title)
    _do_send(instance, verb=verb, target=instance.bill, description=description)
    
pre_delete.connect(record_agenda_bill_removal_action, sender=AgendaBill)
'''

