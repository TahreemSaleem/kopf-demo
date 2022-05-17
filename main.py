import kopf
import kubernetes.client
from kubernetes.client.rest import ApiException
import yaml
from kubernetes.stream import stream
from jinja2 import Template


@kopf.on.create('custom.deployment', 'v1alpha1', 'nginxs')
def create_fn(spec, **kwargs):
    name = kwargs["body"]["metadata"]["name"]
    print("Name is %s\n" % name)
    # Create the deployment spec
    with open('deployment.yaml.jinja2') as file_:
        template = Template(file_.read())
        depl_template = template.render(name=name, replicas=spec.get('replicas', 1),
                                        image=spec.get('image'), port=spec.get('port'))
        deployment = yaml.safe_load(depl_template)
    with open('configmap.yaml.jinja2') as file_:
        template = Template(file_.read())
        configmap_template = template.render(processes=1)
        configmap = yaml.safe_load(configmap_template)

    # With kopf.adopt, we make sure the deployment we create is a child of our custom resource.
    # When we delete the custom resource, its children are also deleted.
    kopf.adopt(deployment)
    kopf.adopt(configmap)
    # Actually create an object by requesting the Kubernetes API.
    api_apps = kubernetes.client.AppsV1Api()
    api_core = kubernetes.client.CoreV1Api()
    try:
        conf = api_core.create_namespaced_config_map(namespace=configmap['metadata']['namespace'], body=configmap)
        depl = api_apps.create_namespaced_deployment(namespace=deployment['metadata']['namespace'], body=deployment)

        # Update the parent's status.
        return {'children': [depl.metadata.uid, conf.metadata.uid]}
    except ApiException as e:
        print("Exception when calling AppsV1Api->create_namespaced_deployment: %s\n" % e)


@kopf.on.create('custom.config', 'v1alpha1', 'nginxs')
@kopf.on.update('custom.config', 'v1alpha1', 'nginxs')
def create_cm(spec, **kwargs):
    name = kwargs["body"]["metadata"]["name"]
    print("Name is %s\n" % name)
    with open('configmap.yaml.jinja2') as file_:
        template = Template(file_.read())
        configmap_template = template.render(processes=spec.get('worker_processes', 1))
        configmap = yaml.safe_load(configmap_template)

    api_core = kubernetes.client.CoreV1Api()
    try:
        api_core.patch_namespaced_config_map(namespace=configmap['metadata']['namespace'],
                                             name=configmap['metadata']['name'], body=configmap)
    except ApiException as e:
        print("Exception when calling AppsV1Api->patch_namespaces_config_map: %s\n" % e)

    try:
        pods = api_core.list_namespaced_pod(namespace='default', label_selector="app=c1-nginx")
    except ApiException as e:
        if e.status != 404:
            print("Unknown error: %s" % e)
            exit(1)

    for item in pods.items:
        pod_name = item.metadata.name
        print("Pod name: " + pod_name)
        # Calling exec and waiting for response
        exec_command = [
            '/bin/sh',
            '-c',
            '/etc/init.d/nginx reload']
        resp = stream(api_core.connect_get_namespaced_pod_exec,
                      pod_name,
                      'default',
                      command=exec_command,
                      stderr=True, stdin=False,
                      stdout=True, tty=False)
        print("Response: " + resp)

