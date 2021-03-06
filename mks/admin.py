from django.contrib import admin
from django.contrib.contenttypes import generic
from django.db.models import Q

from models import Member, Membership, MemberAltname
from models import CoalitionMembership, Correlation, Party
from links.models import Link
from video.models import Video

class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 1

class MemberLinksInline(generic.GenericTabularInline):
    model = Link
    ct_fk_field = 'object_pk'
    extra = 1

class MemberAltnameInline(admin.TabularInline):
    model = MemberAltname
    extra = 1

class MemberRelatedVideosInline(generic.GenericTabularInline):
    model = Video
    ct_fk_field = 'object_pk'
    can_delete = False
    fields = ['title','description','embed_link','group','sticky','hide']
    ordering = ['group','-sticky','-published']
    readonly_fields = ['title','description','embed_link','group']
    extra = 0
    def queryset(self, request):
        qs = super(MemberRelatedVideosInline, self).queryset(request)
        qs = qs.filter(Q(hide=False) | Q(hide=None))
        return qs

class CoalitionMembershipAdmin(admin.ModelAdmin):
    list_display = ('party','start_date','end_date')
admin.site.register(CoalitionMembership, CoalitionMembershipAdmin)


class PartyAdmin(admin.ModelAdmin):
    ordering = ('name',)
#    fields = ('name','start_date','end_date', 'is_coalition','number_of_members')
    list_display = ('name', 'knesset', 'start_date', 'end_date', 'is_coalition',
                    'number_of_members', 'number_of_seats')
    list_filter = ('knesset', )
    inlines = (MembershipInline,)
admin.site.register(Party, PartyAdmin)

def correlation_list_to_string(m, cl):
    return ", ".join(["%s (%.0f)" % ((c.m2 if c.m1 == m else c.m1).get_name_with_link(), 100 * c.normalized_score) for c in cl])

class MemberAdmin(admin.ModelAdmin):
    ordering = ('name',)
#    fields = ('name','start_date','end_date')
    list_display = ('name', 'gender', 'parties_string', 'current_party',
                    'is_current', 'current_position')
    list_editable = ('is_current', 'current_position')
    search_fields = ['name']
    inlines = (MembershipInline, MemberLinksInline, MemberAltnameInline, MemberRelatedVideosInline)
    list_filter = ('current_party__knesset', 'gender')

    # A template for a very customized change view:
    change_form_template = 'admin/simple/change_form_with_extra.html'

    def change_view(self, request, object_id, extra_context=None):
        m = Member.objects.get(id=object_id)
        corrs = Correlation.objects.filter(m1=m.id).order_by('normalized_score')
        
        my_context = {
            'extra': {
                'hi_corr': correlation_list_to_string(m, corrs[:4]),
                'low_corr': correlation_list_to_string(m, corrs[-3:]),
            }
        }
        return super(MemberAdmin, self).change_view(request, object_id,
                                                    extra_context=my_context)

    def queryset(self, request):
        return super(MemberAdmin, self).queryset(request).select_related('current_party')
admin.site.register(Member, MemberAdmin)


class CorrelationAdmin(admin.ModelAdmin):
    ordering = ('-normalized_score',)
admin.site.register(Correlation, CorrelationAdmin)

class MembershipAdmin(admin.ModelAdmin):
    ordering = ('member__name',)
admin.site.register(Membership, MembershipAdmin)
