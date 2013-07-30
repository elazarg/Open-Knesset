# encoding: utf-8
import datetime
from django.db.models.signals import post_save, pre_delete, post_delete
from django.contrib.contenttypes.models import ContentType
from planet.models import Feed, Post
from actstream import action
from actstream.models import Follow
from knesset.utils import disable_for_loaddata

def _do_send(instance, **kwargs):
    kwargs['timestamp'] = datetime.datetime.now()
    action.send(instance.agenda, **kwargs)
    
_fmt_created = u'agenda {atype} ascribed', u'agenda "{name}" ascribed to {atype} "{title}"'
_fmt_updated = u'agenda {atype} relation updated', u'relation between agenda "{name}" and {atype} "{title}" was updated'
_fmt_removed = u'agenda {atype} removed', u'agenda "{name}" removed from {atype} "{title}"'

#FIX:
#@params should be based on naming convensions. probably getattr(aclass, atype).title
def Listener(key_attr, titlegetter):
    @disable_for_loaddata
    def record_ascription_action(sender, created, instance, **kwargs):
        if created:  verb, fmt = _fmt_created
        else:        verb, fmt = _fmt_updated
        description = fmt.format(name=instance.agenda.name, title=titlegetter(instance), atype=key_attr)
        _do_send(instance, verb=verb.format(atype=key_attr), target=instance, description=description)

    @disable_for_loaddata
    def record_removal_action(sender, instance, **kwargs):
        verb, fmt = _fmt_removed
        description = fmt.format(name=instance.agenda.name, title=titlegetter(instance), atype=key_attr)
        _do_send(instance, verb=verb.format(atype=key_attr), target=getattr(instance, key_attr), description=description)
    
    def wrap(aclass):
        aclass._record_ascription_action = record_ascription_action
        aclass._record_removal_action = record_removal_action
        
        post_save.connect(record_ascription_action, sender=aclass)
        pre_delete.connect(record_removal_action, sender=aclass)
        return aclass
    return wrap

def Follower(agenda_class):
    @disable_for_loaddata
    def update_num_followers(sender, instance, **kwargs):
        agenda = instance.actor
        if isinstance(agenda, agenda_class):
            agenda.num_followers = Follow.objects.filter(
                content_type=ContentType.objects.get(
                        app_label="agendas",
                        model="agenda").id,
                object_id=agenda.id).count()
            agenda.save()

    post_delete.connect(update_num_followers, sender=Follow)
    post_save.connect(update_num_followers, sender=Follow)
    return agenda_class
