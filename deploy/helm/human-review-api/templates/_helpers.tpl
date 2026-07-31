{{- define "human-review-api.fullname" -}}
{{- .Release.Name }}-human-review-api
{{- end }}

{{- define "human-review-api.labels" -}}
app.kubernetes.io/name: human-review-api
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "human-review-api.selectorLabels" -}}
app.kubernetes.io/name: human-review-api
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "human-review-api.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "human-review-api.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
