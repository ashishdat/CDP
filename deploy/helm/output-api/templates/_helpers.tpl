{{- define "output-api.fullname" -}}
{{- .Release.Name }}-output-api
{{- end }}

{{- define "output-api.labels" -}}
app.kubernetes.io/name: output-api
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "output-api.selectorLabels" -}}
app.kubernetes.io/name: output-api
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "output-api.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "output-api.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
