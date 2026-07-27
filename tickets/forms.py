from django import forms


class XMLUploadForm(forms.Form):
    xml_file = forms.FileField(
        label='Archivo XML de HESK',
        help_text='Selecciona el archivo .xml exportado desde la plataforma de tickets.',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.xml'}),
    )

    def clean_xml_file(self):
        f = self.cleaned_data['xml_file']
        if not f.name.lower().endswith('.xml'):
            raise forms.ValidationError('El archivo debe tener extensión .xml')
        return f
